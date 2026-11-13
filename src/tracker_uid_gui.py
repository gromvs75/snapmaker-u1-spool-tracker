"""Local GUI bridge: all mutations go through AccountingOwner, no legacy writes."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import secrets
import time
from tracker_uid_catalog import UidCatalog


def serve(owner, fleet, port=0, *, status_reader=None, sender=None):
    token=secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def reply(self,status,value,kind='application/json'):
            raw=json.dumps(value,ensure_ascii=False).encode() if kind=='application/json' else value.encode()
            self.send_response(status);self.send_header('Content-Type',kind+'; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def authorized(self):
            return (self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}'
                    and self.headers.get('X-Tracker-Token')==token
                    and self.headers.get('Origin',f'http://127.0.0.1:{self.server.server_port}')==f'http://127.0.0.1:{self.server.server_port}')
        def do_GET(self):
            if self.headers.get('Host')!=f'127.0.0.1:{self.server.server_port}':return self.reply(403,{'error':'Invalid host'})
            if self.path=='/favicon.ico':
                self.send_response(204);self.end_headers();return
            if self.path=='/':
                html=Path(__file__).with_name('tracker_uid_gui.html').read_text(encoding='utf-8')
                return self.reply(200,html.replace('<script>','<script>const TOKEN='+json.dumps(token)+';'),'text/html')
            if self.path!='/api/state':return self.reply(404,{'error':'Not found'})
            if not self.authorized():return self.reply(403,{'error':'Forbidden'})
            locations=owner.call('refresh');state=owner.call('inspect')
            from tracker_uid_presentation import history_presentation
            state.update(owner.call('library_snapshot'))
            state['delivery']=owner.call('delivery_list')
            state['delivery_enabled']=sender is not None
            state['connections']=owner.call('connection_state') if hasattr(owner,'connected') else None
            for job in state['jobs']: job['presentation']=history_presentation(job,state['debits'],state['reviews'])
            state['active_spools']=owner.call('active_spools')
            state['occupied']=[r for r in locations if r.get('identity_mode')!='manual']
            for assignment in state['manual_assignments']:
                tagged=next((r for r in state['occupied'] if r['printer_id']==assignment['printer_id'] and r['channel']==assignment['channel']),None)
                assignment['state']='conflict' if tagged else ('manual_confirmed' if assignment['confirmed'] else 'manual_unconfirmed')
            state['printers']=[{'id':pid,'name':s.get('name',{'a':'U1_1','b':'U1_2'}.get(pid,pid)),'ready':s['state']=='ready'} for pid,s in fleet.snapshot().items()]
            for p in state['printers']:p['name']=state['settings']['values'].get('printer_names',{}).get(p['id'],p['name'])
            self.reply(200,state)
        def do_POST(self):
            if not self.authorized():return self.reply(403,{'error':'Forbidden'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<(46*1024*1024 if self.path in ('/api/validate_backup','/api/restore_backup') else 16384):raise ValueError('Invalid request size')
                data=json.loads(self.rfile.read(size))
                if self.path in ('/api/connections_start','/api/connections_stop','/api/validate_backup','/api/restore_backup') and not hasattr(owner,'connected'):
                    raise ValueError('Managed session required')
                if self.path in ('/api/tag_preview','/api/tag_register'):
                    if status_reader is None:raise ValueError('Проверка принтера недоступна.')
                    if 'observation' in data or 'fleet' in data:raise ValueError('Неверные параметры регистрации.')
                    snapshot=fleet.snapshot().get(data['printer_id'],{})
                    if snapshot.get('state')!='ready':raise ValueError('Нет связи с принтером.')
                    checked=time.monotonic()
                    observation={'state':status_reader(data['printer_id']), 'checked_at':checked,
                                 'connection_token':UidCatalog.connection_token(snapshot)}
                    return self.reply(200,owner.call(self.path.removeprefix('/api/'),**data,observation=observation))
                if self.path=='/api/resolve':
                    if not {'job_key','expected_version','confirmed','accept_unaccounted'}<=set(data) or set(data)-{'job_key','expected_version','confirmed','accept_unaccounted','mode'}:
                        raise ValueError('Неверные параметры разрешения задания.')
                    if status_reader is None:raise ValueError('Проверка состояния принтера недоступна.')
                    job=next((j for j in owner.call('inspect')['jobs'] if j['job_key']==data['job_key']),None)
                    if job is None:raise ValueError('Задание не найдено.')
                    snapshot=fleet.snapshot().get(job['printer_id'],{})
                    checked=time.monotonic()
                    observation={'state':status_reader(job['printer_id']), 'checked_at':checked,
                                 'connection_token':UidCatalog.connection_token(snapshot)}
                    return self.reply(200,owner.call('resolve_interrupted',**data,observation=observation))
                if self.path=='/api/delivery_review':
                    if sender is None:raise ValueError('Отправка и сверка недоступны в этом сеансе.')
                    return self.reply(200,sender.review(**data))
                if self.path=='/api/delivery_send':
                    if sender is None:raise ValueError('Spoolman sender is not enabled for this session.')
                    if data.get('confirmed') is not True or set(data)-{'confirmed','operation_id','expected_revision'}:raise ValueError('Explicit send confirmation required')
                    if ('operation_id' in data)!=('expected_revision' in data):raise ValueError('Operation and revision required together')
                    return self.reply(200,{'status':sender.send_one(data.get('operation_id'),data.get('expected_revision'))})
                commands={'/api/connections_start':'connect_printers','/api/connections_stop':'disconnect_printers','/api/backup_package':'backup_package','/api/validate_backup':'validate_backup','/api/restore_backup':'restore_backup','/api/delivery_decide':'delivery_decide','/api/delivery_audit':'delivery_audit','/api/create':'create_spool','/api/detach':'detach_spool','/api/settings':'save_settings',
                          '/api/compare':'compare_name','/api/rename':'rename_from_remote','/api/catalog':'remote_catalog',
                          '/api/backup':'export_backup'}
                if self.path=='/api/restore_backup' and sender is not None:
                    with sender._mutex:
                        return self.reply(200,owner.call('restore_backup',**data))
                if self.path in commands:
                    return self.reply(200,owner.call(commands[self.path],**data))
                if self.path=='/api/refresh_catalog':
                    from tracker_uid_spoolman import Client
                    settings=owner.call('settings')
                    url=settings['values'].get('spoolman_url','')
                    try: items=Client(url).catalog()
                    except Exception:
                        if url:owner.call('cache_catalog',url,None)
                        raise ValueError('Spoolman недоступен. Каталог не обновлён.')
                    return self.reply(200,owner.call('cache_catalog',url,items))
                command={'/api/assign' :'assign_manual','/api/transfer':'transfer_manual'}.get(self.path)
                if not command:return self.reply(404,{'error':'Not found'})
                if not isinstance(data.get('expected_version'),str) or data.get('confirmed') is not True:raise ValueError('Подтвердите физическое назначение.')
                result=owner.call(command,**data)
                self.reply(200,result)
            except (ValueError,TypeError,KeyError,OSError,TimeoutError) as exc:self.reply(409,{'error':str(exc)})
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)
