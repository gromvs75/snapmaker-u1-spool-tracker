"""HTTP enrollment adapter. Browser gets opaque, expiring review IDs, not tickets."""
import secrets
import threading
import time

from tracker_rfid import RfidWorker
from tracker_rfid_lookup import resolve_names
from tracker_uid_catalog import UidCatalog


class Enrollment:
    def __init__(self, owner, fleet, status_reader, sender, *, client_factory=None):
        self.owner=owner;self.fleet=fleet;self.status_reader=status_reader;self.sender=sender
        self.client_factory=client_factory;self.lock=threading.Lock();self.reviews={}

    def proof(self, pid):
        if self.status_reader is None:raise ValueError('Проверка принтера недоступна.')
        snapshot=self.fleet.snapshot().get(pid,{})
        checked=time.monotonic()
        state=self.status_reader(pid)
        if state not in ('standby','complete','cancelled','error'):
            raise ValueError('Сначала остановите печать.')
        return dict(state=state,checked_at=checked,connection_token=UidCatalog.connection_token(snapshot))

    def allowed(self, url):
        if self.sender is None or not self.sender.permits(url):
            raise ValueError('Настройте и разрешите Spoolman для этого сеанса.')

    def preview(self, printer_id, channel, uid):
        with self.lock:
            snapshot=self.fleet.snapshot().get(printer_id,{})
            observed=snapshot.get('channels',{}).get(channel,{})
            if observed.get('uid')!=uid:raise ValueError('Метка изменилась. Проверьте снова.')
            if not observed.get('tag'):return dict(available=False)
            self.proof(printer_id)
            ticket=self.owner.call('rfid_prepare',printer_id,channel,review=True)
            if ticket['tag']['uid']!=uid or ticket['sid']:raise ValueError('Метка уже зарегистрирована или изменилась.')
            self.allowed(ticket['url'])
            candidates=self.owner.call('rfid_candidates',ticket)
            now=time.monotonic()
            self.reviews={k:v for k,v in self.reviews.items() if now-v['ticket']['checked_at']<120}
            if len(self.reviews)>=128:self.reviews.pop(next(iter(self.reviews)))
            key=secrets.token_urlsafe(24)
            self.reviews[key]=dict(ticket=ticket,candidates={s['spool_id']:s for s in candidates})
            tag=ticket['tag'];config=ticket['config'];names=resolve_names(tag,config)
            known=bool(names['material'] and tag['color'] and names['manufacturer'] not in ('Unknown','TigerTag','QIDI-compatible'))
            density=next((config.get('densities',{}).get(k) for k in (tag['material_id'],tag['name']) if k in config.get('densities',{})),None)
            return dict(available=True,review_id=key,uid=uid,format=tag['format'],manufacturer=names['manufacturer'],
                        material=names['material'],colors=tag['colors'],name=tag['name'],url=ticket['url'],
                        can_create=ticket['can_create'] and known,candidates=candidates,
                        reason='' if known else 'Материал, производитель или цвет ещё не определён.',
                        defaults=dict(remaining_g=None,density=density,diameter=tag['diameter_mm'] or config.get('diameters',{}).get(tag['material_id']),
                                      nominal=tag['nominal_weight_g'] or config.get('nominal_weights',{}).get(tag['material_id'])),
                        fixed=dict(diameter=tag['diameter_mm'] is not None,nominal=tag['nominal_weight_g'] is not None))

    def confirm(self, review_id, action, *, confirmed=False, values=None, spool_id=None):
        with self.lock:
            if confirmed is not True:raise ValueError('Подтвердите катушку и выбранное действие.')
            review=self.reviews.get(review_id)
            if not review:raise ValueError('Проверка устарела. Проверьте метку снова.')
            intent=[action,values,spool_id]
            if 'intent' in review:
                if review['intent']!=intent:raise ValueError('Решение изменилось после отправки. Проверьте результат.')
                if 'result' in review:return review['result']
                raise ValueError('Запрос уже отправлялся. Проверьте метку снова; повторная катушка не создаётся.')
            ticket=review['ticket'];self.allowed(ticket['url'])
            observation=self.proof(ticket['printer_id'])
            if action=='new':
                if spool_id is not None:raise ValueError('Неверные параметры новой катушки.')
                ticket=self.owner.call('rfid_approve',ticket,values,confirmed=confirmed,observation=observation)
            elif action=='pair':
                if values is not None or spool_id not in review['candidates']:raise ValueError('Выберите катушку из проверенного списка.')
                self.owner.call('rfid_pair_review',ticket,spool_id,review['candidates'][spool_id]['revision'],confirmed=confirmed,observation=observation)
                ticket=self.owner.call('rfid_prepare',ticket['printer_id'],ticket['channel'])
            else:raise ValueError('Неверное действие.')
            review['intent']=intent
            options=dict(interactive=True)
            if self.client_factory:options['client_factory']=self.client_factory
            worker=RfidWorker(self.owner,[ticket['url']],**options)
            try:
                result=worker.scan(ticket['printer_id'],ticket['channel'],expected_ticket=ticket)
            except (ValueError,OSError,TimeoutError):
                # Pairing is already committed and must remain usable offline.
                if action!='pair':raise
                row=next(s for s in self.owner.call('library_snapshot')['spools'] if s['spool_id']==spool_id)
                result=dict(spool_id=spool_id,remaining_mg=row['remaining_mg'],balance_source='local',
                            warning='Метка привязана. Сверка Spoolman пока не завершена; сохранён локальный остаток.')
            review['result']=result
            return result


def explain_error(exc):
    messages={
        'RFID observation or balance changed':'Метка, соединение или остаток изменились. Нажмите «Проверить снова».',
        'RFID ticket expired':'Проверка устарела. Нажмите «Проверить снова».',
        'RFID enrollment disabled':'Настройте Spoolman и включите чтение или отправку в его настройках.',
        'Fresh idle printer required':'Нужна связь с принтером и остановленная печать.',
        'Fresh tag required':'Нет свежей считанной метки. Нажмите «Проверить снова».',
        'Previous POST outcome unknown; reconcile, never retry':'Spoolman не подтвердил прошлую запись. Нужна сверка; повторно катушка не создаётся.',
        'Unsupported Spoolman version':'Для этого сценария нужен Spoolman 0.27.1.',
        'Remove the manual head assignment first':'Сначала снимите ручное назначение катушки на этой головке.',
    }
    if isinstance(exc,(OSError,TimeoutError)):
        return 'Spoolman не ответил. Нажмите «Проверить снова» для сверки результата; повторная запись защищена от дубликатов.'
    return messages.get(str(exc),str(exc))
