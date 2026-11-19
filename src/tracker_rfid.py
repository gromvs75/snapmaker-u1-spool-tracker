"""Opt-in RFID enrollment and Spoolman reconciliation, with durable POST fences.

SQLite methods run on AccountingOwner. HTTP runs only in RfidWorker. No printer
commands, tag writes, or implicit retries of writes with an unknown outcome.
"""
import json
import copy
import threading
import time
import uuid

from tracker_rfid_metadata import product, validate_tag, roll_key
from tracker_rfid_lookup import resolve_names
from tracker_uid_accounting import AccountingConflict, mg
from tracker_uid_library import revision
from tracker_uid_spoolman import Client, catalog_item, endpoint
from tracker_uid_tags import Tags


class RfidRegistry:
    def __init__(self, library, delivery):
        self.library = library
        self.delivery = delivery
        self.accounting = library.accounting
        self.catalog = library.catalog
        self.db = library.db
        self.tags = Tags(self.accounting)
        self.db.execute('''CREATE TABLE IF NOT EXISTS uid_rfid_creations (
            url TEXT NOT NULL, marker TEXT NOT NULL, attempted_at REAL NOT NULL,
            PRIMARY KEY(url,marker))''')
        self.db.commit()

    def approve_usage(self, url, *, fleet):
        """Opt-in policy for new, proved debits only; uncertain writes stay held."""
        settings = self.library.settings()['values']
        config = settings.get('rfid', {})
        if (not config.get('enabled') or not config.get('send_usage')
                or settings.get('spoolman_mode') != 'send' or settings.get('spoolman_url') != url):
            return []
        delivery = self.delivery
        pending = []
        with self.accounting.transaction():
            for row in delivery._rows():
                if row['state'] not in ('held', 'pending') or row['url'] != url:
                    continue
                if not self.db.execute('SELECT 1 FROM uid_rfid_rolls WHERE spool_id=?', (row['spool_id'],)).fetchone():
                    continue
                if row['state'] == 'held':
                    row = delivery._transition(row, 'pending', 'Explicit RFID send_usage policy; ledger checked again at claim')
                pending.append(dict(operation_id=row['operation_id'], revision=row['revision']))
        return pending

    def _local_version(self, sid):
        return revision([
            [tuple(r) for r in self.db.execute('SELECT * FROM uid_spools WHERE spool_id=?', (sid,))],
            [tuple(r) for r in self.db.execute('SELECT * FROM uid_remote_links WHERE spool_id=?', (sid,))],
            [tuple(r) for r in self.db.execute('SELECT * FROM uid_remote_outbox WHERE spool_id=? ORDER BY rowid', (sid,))],
        ])

    def prepare(self, printer_id, channel, *, fleet, review=False):
        settings = self.library.settings()
        values = settings['values']
        config = values.get('rfid', {})
        if (not review and not config.get('enabled')) or values.get('spoolman_mode', 'off') == 'off':
            raise AccountingConflict('RFID enrollment disabled')
        url = endpoint(values.get('spoolman_url'))
        snapshot = fleet.get(printer_id, {})
        if (snapshot.get('state') != 'ready' or not snapshot.get('printer_connected')
                or snapshot.get('print_state') not in ('standby', 'complete', 'cancelled', 'error')):
            raise AccountingConflict('Fresh idle printer required')
        observed = snapshot.get('channels', {}).get(channel, {})
        if observed.get('state') != 'present' or observed.get('age_seconds', 301) > 300:
            raise AccountingConflict('Fresh tag required')
        tag = validate_tag(observed.get('tag'), observed.get('uid'))
        approval = config.get('approvals', {}).get(tag['identity'])
        if approval and approval['product'] != product(tag):
            raise AccountingConflict('Approved roll metadata changed')
        config = copy.deepcopy(config)
        if approval:
            for key, code, field in (('initial_balances',tag['identity'],'remaining_g'),
                                     ('densities',tag['material_id'],'density'),
                                     ('diameters',tag['material_id'],'diameter'),
                                     ('nominal_weights',tag['material_id'],'nominal')):
                config.setdefault(key,{})[code] = approval[field]
        with self.accounting.transaction():
            locations = self.catalog._reconcile(fleet)
            row = next((r for r in locations if (r['printer_id'], r['channel']) == (printer_id, channel)), None)
            if not row or row['state'] not in ('recognized', 'needs_registration'):
                raise AccountingConflict('Conflicting spool location')
            roll = self.catalog.rfid_roll(tag)
            if not roll and tag['format'] != 'bambu' and row.get('spool'):
                roll = self.db.execute('SELECT * FROM uid_rfid_rolls WHERE spool_id=?', (row['spool']['spool_id'],)).fetchone()
            sid = roll['spool_id'] if roll else None
            if roll and json.loads(roll['product']) != product(tag):
                raise AccountingConflict('Roll metadata changed')
            if row.get('spool') and row['spool']['spool_id'] != sid:
                raise AccountingConflict('UID already belongs to another registration')
            if sid and self.catalog.rfid_key_conflict(tag, sid):
                raise AccountingConflict('Physical roll ID changed')
            if sid and tag['identity'] != roll['identity'] and not self.catalog.spool(tag['uid']) and self.db.execute(
                    'SELECT 1 FROM uid_rfid_creations WHERE url=? AND marker=?',
                    (url, 'Tracker RFID '+tag['identity'])).fetchone():
                raise AccountingConflict('Creation was attempted for this tag; reconcile it before pairing')
            self.tags._guard(printer_id, sid)
            if self.db.execute('SELECT 1 FROM manual_assignments WHERE printer_id=? AND channel=?', (printer_id, channel)).fetchone():
                raise AccountingConflict('Remove the manual head assignment first')
            link = self.db.execute('SELECT * FROM uid_remote_links WHERE spool_id=?', (sid,)).fetchone()
            if sid and (not link or link['url'] != url or self.catalog.archived(sid)):
                raise AccountingConflict('Spool link changed or spool archived')
            pending = bool(sid and self.db.execute("SELECT 1 FROM uid_remote_outbox WHERE spool_id=? AND state NOT IN ('sent','resolved')", (sid,)).fetchone())
            return dict(printer_id=printer_id, channel=channel, tag=tag, url=url,
                        identity=roll['identity'] if roll else (roll_key(tag) or tag['identity']),
                        config=config, approved=bool(approval), review=review, settings_revision=settings['revision'],
                        token=self.catalog.connection_token(snapshot), sequence=observed.get('sequence'),
                        sid=sid, link=dict(link) if link else None, pending=pending,
                        local_version=self._local_version(sid), checked_at=time.monotonic(),
                        can_create=bool((review or approval or config.get('allow_create')) and values.get('spoolman_mode') == 'send'))

    def _recheck(self, ticket, fleet):
        if not 0 <= time.monotonic() - ticket['checked_at'] <= 120:
            raise AccountingConflict('RFID ticket expired')
        current = self.prepare(ticket['printer_id'], ticket['channel'], fleet=fleet, review=ticket.get('review',False))
        for key in ('tag', 'identity', 'url', 'settings_revision', 'token', 'sequence', 'sid', 'local_version'):
            if current[key] != ticket[key]:
                raise AccountingConflict('RFID observation or balance changed')
        return current

    def recheck(self, ticket, *, fleet):
        return self._recheck(ticket, fleet)

    def _proof(self, ticket, observation, fleet):
        with self.accounting.transaction():
            self.tags._observed(ticket['printer_id'], ticket['channel'], ticket['tag']['uid'], fleet, observation)

    def candidates(self, ticket, *, fleet):
        self._recheck(ticket, fleet)
        if ticket['tag']['format']=='bambu':return []
        occupied={r['spool']['spool_id'] for r in self.catalog.reconcile(fleet) if r.get('spool')}
        result=[]
        for roll in self.db.execute('SELECT * FROM uid_rfid_rolls ORDER BY spool_id').fetchall():
            sid=roll['spool_id']
            if json.loads(roll['product'])!=product(ticket['tag']) or sid in occupied or self.catalog.archived(sid):continue
            if self.catalog.rfid_key_conflict(ticket['tag'], sid):continue
            link=self.db.execute('SELECT * FROM uid_remote_links WHERE spool_id=?',(sid,)).fetchone()
            if not link or link['url']!=ticket['url']:continue
            if self.db.execute('SELECT 1 FROM manual_assignments WHERE spool_id=?',(sid,)).fetchone():continue
            try:self.tags._guard(ticket['printer_id'],sid)
            except AccountingConflict:continue
            spool=dict(self.db.execute('SELECT * FROM uid_spools WHERE spool_id=?',(sid,)).fetchone())
            result.append(dict(spool,remote_id=link['remote_id'],revision=self._local_version(sid)))
        return result

    def approve(self, ticket, values, *, fleet, observation, confirmed=False):
        if confirmed is not True:raise AccountingConflict('Подтвердите новую катушку.')
        self._recheck(ticket,fleet);self._proof(ticket,observation,fleet)
        if not ticket['can_create'] or ticket['sid']:raise AccountingConflict('Включите отправку в настройках Spoolman.')
        if not isinstance(values,dict) or set(values)!={'remaining_g','density','diameter','nominal'}:
            raise ValueError('Укажите остаток, плотность, диаметр и массу новой катушки.')
        tag=ticket['tag'];names=resolve_names(tag,ticket['config'])
        if not names['material'] or not tag['color'] or names['manufacturer'] in ('Unknown','TigerTag','QIDI-compatible'):
            raise ValueError('Материал, производитель или цвет ещё не определён.')
        for field,prop in (('diameter','diameter_mm'),('nominal','nominal_weight_g')):
            if tag[prop] is not None and values[field]!=tag[prop]:raise ValueError('Параметры отличаются от прочитанной метки.')
        settings=self.library.settings();config=copy.deepcopy(settings['values'].get('rfid',{}))
        config['enabled']=True
        approval=dict(values,product=product(tag))
        old=config.get('approvals',{}).get(tag['identity'])
        if old and {k:v for k,v in old.items() if k!='catalog'}!=approval:raise AccountingConflict('Решение уже отправлено. Сначала проверьте результат в Spoolman.')
        if old:
            approval=old
        else:
            from tracker_spoolmandb import suggest
            lookup=suggest(tag,names)
            if lookup['status']=='suggested':
                candidate=lookup['candidates'][0]
                fields=[field for field,key in (('density','density'),('diameter','diameter'),('nominal','weight'))
                        if values[field]==candidate[key]]
                approval['catalog']=dict(source='SpoolmanDB',revision=lookup['revision'],
                                         product_id=candidate['id'],confirmed_fields=fields,
                                         match='suggested-by-properties')
        config.setdefault('approvals',{})[tag['identity']]=approval
        self.library.save_settings({'rfid':config},ticket['settings_revision'])
        return self.prepare(ticket['printer_id'],ticket['channel'],fleet=fleet)

    def pair_review(self, ticket, spool_id, expected_spool, *, fleet, observation, confirmed=False):
        self._recheck(ticket,fleet);self._proof(ticket,observation,fleet)
        if self._local_version(spool_id)!=expected_spool:raise AccountingConflict('Остаток катушки изменился. Проверьте выбор снова.')
        result=self.pair(ticket,spool_id,confirmed,fleet=fleet)
        settings=self.library.settings();config=copy.deepcopy(settings['values'].get('rfid',{}))
        if not config.get('enabled'):
            config['enabled']=True
            self.library.save_settings({'rfid':config},settings['revision'])
        return result

    def claim(self, ticket, marker, *, fleet):
        current = self._recheck(ticket, fleet)
        if not current['can_create'] or not isinstance(marker, str) or len(marker) > 150:
            raise AccountingConflict('Spoolman creation disabled')
        with self.accounting.transaction():
            old = self.db.execute('SELECT 1 FROM uid_rfid_creations WHERE url=? AND marker=?', (ticket['url'], marker)).fetchone()
            if old:
                raise AccountingConflict('Previous POST outcome unknown; reconcile, never retry')
            self.db.execute('INSERT INTO uid_rfid_creations VALUES(?,?,?)', (ticket['url'], marker, time.time()))
        return True

    def pair(self, ticket, spool_id, confirmed=False, *, fleet):
        """Explicitly identify the other side. Never merges existing inventories."""
        self._recheck(ticket, fleet)
        tag = ticket['tag']
        if confirmed is not True or ticket['sid'] is not None or tag['format'] == 'bambu':
            raise AccountingConflict('Confirm an unregistered second-side tag')
        with self.accounting.transaction():
            if self.db.execute('SELECT 1 FROM uid_rfid_creations WHERE url=? AND marker=?',
                               (ticket['url'], 'Tracker RFID '+ticket['identity'])).fetchone():
                raise AccountingConflict('Creation was attempted for this tag; reconcile it before pairing')
            roll = self.db.execute('SELECT * FROM uid_rfid_rolls WHERE spool_id=?', (spool_id,)).fetchone()
            if not roll or json.loads(roll['product']) != product(tag):
                raise AccountingConflict('Second tag properties differ from the selected roll')
            if self.catalog.rfid_key_conflict(tag, spool_id):
                raise AccountingConflict('Physical roll ID changed')
            link = self.db.execute('SELECT * FROM uid_remote_links WHERE spool_id=?', (spool_id,)).fetchone()
            if not link or link['url'] != ticket['url'] or self.catalog.archived(spool_id):
                raise AccountingConflict('Selected spool is unavailable')
            self.tags._guard(ticket['printer_id'], spool_id)
            locations = self.catalog._reconcile(fleet)
            if any((r.get('spool') or {}).get('spool_id') == spool_id for r in locations):
                raise AccountingConflict('Remove the previous spool location before pairing')
            if self.db.execute('SELECT 1 FROM manual_assignments WHERE spool_id=?', (spool_id,)).fetchone():
                raise AccountingConflict('Remove the manual assignment before pairing')
            if self.catalog.spool(tag['uid']):
                raise AccountingConflict('Tag already belongs to a spool')
            self.db.execute('INSERT INTO uid_rfid_aliases VALUES(?,?)', (tag['uid'], spool_id))
        return dict(spool_id=spool_id, identity=roll['identity'], uid=tag['uid'])

    def commit(self, ticket, raw=None, *, fleet):
        self._recheck(ticket, fleet)
        tag, sid = ticket['tag'], ticket['sid']
        item = catalog_item(raw) if raw is not None else None
        if item and (item['archived'] or item['remaining_g'] is None):
            raise AccountingConflict('Remote spool unavailable')
        if item and ticket['link'] and item['id'] != ticket['link']['remote_id']:
            raise AccountingConflict('Remote identity changed')
        if not sid and item is None:
            raise AccountingConflict('Unknown spool cannot be created offline')
        with self.accounting.transaction():
            if not sid:
                existing = self.db.execute('SELECT spool_id FROM uid_remote_links WHERE url=? AND remote_id=?', (ticket['url'], item['id'])).fetchone()
                if existing:
                    sid = existing[0]
                    spool = self.db.execute('SELECT * FROM uid_spools WHERE spool_id=?', (sid,)).fetchone()
                    self.tags._candidate(dict(spool), ticket['printer_id'], ticket['channel'])
                    if self.db.execute('SELECT 1 FROM uid_rfid_rolls WHERE spool_id=?', (sid,)).fetchone():
                        raise AccountingConflict('Remote spool belongs to another roll')
                    if self.db.execute("SELECT 1 FROM uid_remote_outbox WHERE spool_id=? AND state NOT IN ('sent','resolved')", (sid,)).fetchone():
                        raise AccountingConflict('Resolve pending consumption before enrollment')
                    self.db.execute('UPDATE uid_spools SET uid=? WHERE spool_id=?', (tag['uid'], sid))
                else:
                    sid = uuid.uuid4().hex
                    self.db.execute('INSERT INTO uid_spools VALUES(?,?,?,?)', (sid, tag['uid'], item['name'], mg(item['remaining_g'])))
                    self.db.execute('INSERT INTO uid_remote_links VALUES(?,?,?)', (sid, ticket['url'], item['id']))
                self.db.execute('INSERT INTO uid_rfid_rolls VALUES(?,?,?)', (ticket['identity'], sid, json.dumps(product(tag), sort_keys=True)))
                names = resolve_names(tag, ticket['config'])
                details = dict(material=names['material'] or item['material'], color='#'+tag['color'].lower() if tag['color'] else None,
                               manufacturer=names['manufacturer'], lookup_sources=names['lookup_sources'],
                               diameter=tag['diameter_mm'] or raw['filament'].get('diameter'),
                               rfid=tag, initial_weight_source='Spoolman; nominal is not measured remaining')
                approved=ticket['config'].get('approvals',{}).get(tag['identity'],{})
                if approved.get('catalog'):
                    details['catalog_match']=copy.deepcopy(approved['catalog'])
                from spool_identity import calibration
                # Density comes from the configured/catalogued Spoolman material,
                # never from the RFID tag or a guessed generic material family.
                details['calibration'] = calibration(dict(uid=tag['uid'], diameter_mm=raw['filament'].get('diameter'),
                                                          density_g_cm3=raw['filament'].get('density')))
                self.db.execute('INSERT OR REPLACE INTO spool_details VALUES(?,?)', (sid, json.dumps(details)))
            other = self.catalog.spool(tag['uid'])
            if other and other['spool_id'] != sid:
                raise AccountingConflict('Chip already belongs to another spool')
            self.db.execute('INSERT OR IGNORE INTO uid_rfid_aliases VALUES(?,?)', (tag['uid'], sid))
            key = roll_key(tag)
            if key:
                if self.catalog.rfid_key_conflict(tag, sid):
                    raise AccountingConflict('Physical roll ID changed')
                self.db.execute('INSERT OR IGNORE INTO uid_rfid_roll_keys VALUES(?,?)', (key, sid))
            if item and not ticket['pending']:
                self.db.execute('UPDATE uid_spools SET remaining_mg=? WHERE spool_id=?', (mg(item['remaining_g']), sid))
            spool = dict(self.db.execute('SELECT * FROM uid_spools WHERE spool_id=?', (sid,)).fetchone())
        return dict(spool, identity=ticket['identity'], balance_source='local' if item is None or ticket['pending'] else 'spoolman')


class RfidWorker:
    def __init__(self, owner, allowed_urls, *, client_factory=Client, interval=3, interactive=False):
        self.owner = owner
        self.interactive = interactive
        self.allowed_urls = frozenset(endpoint(u) for u in allowed_urls)
        self.client_factory = client_factory
        self.interval = interval
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.thread = None
        self.results = {}

    def _list(self, client, kind):
        result = []
        for offset in range(0, 10000, 100):
            if self.stop_event.is_set(): raise AccountingConflict('RFID worker stopping')
            path = '/'+kind+'?limit=100&offset='+str(offset)
            if kind == 'spool': path += '&allow_archived=true'
            rows, _ = client.request('GET', path)
            if not isinstance(rows, list): raise ValueError('Invalid Spoolman list')
            result.extend(rows)
            if len(rows) < 100:
                if len({r['id'] for r in result}) != len(result):
                    raise AccountingConflict('Spoolman list changed during paging')
                return result
        raise ValueError('Spoolman list too large')

    def _find(self, client, kind, marker):
        matches = [r for r in self._list(client, kind) if marker in (r.get('comment') or '').splitlines()]
        if len(matches) > 1: raise AccountingConflict('Duplicate RFID identity in Spoolman')
        return matches[0] if matches else None

    def _create(self, ticket, client, kind, marker, body):
        # Durable fence precedes every POST. A later scan may adopt a matching
        # record after a lost response, but absence is never proof of no write.
        if self.stop_event.is_set(): raise AccountingConflict('RFID worker stopping')
        self.owner.call('rfid_claim', ticket, marker)
        result, _ = client.request('POST', '/'+kind, dict(body, comment=marker))
        if type(result.get('id')) is not int or result['id'] <= 0:
            raise ValueError('Invalid creation acknowledgement')
        return result

    def scan(self, printer_id, channel, *, expected_ticket=None):
        with self.lock:
            ticket = (self.owner.call('rfid_recheck',expected_ticket) if expected_ticket is not None
                      else self.owner.call('rfid_prepare', printer_id, channel))
            if self.interactive and not ticket['sid'] and (not ticket['approved'] or expected_ticket is None):
                raise AccountingConflict('Подтвердите новую катушку или привяжите вторую метку.')
            if ticket['url'] not in self.allowed_urls:
                raise AccountingConflict('RFID server is not allowed in this session')
            if ticket['pending']:
                return self.owner.call('rfid_commit', ticket)
            client = self.client_factory(ticket['url'])
            try:
                info, _ = client.request('GET', '/info')
                if info.get('version') != '0.27.1': raise ValueError('Unsupported Spoolman version')
                marker = 'Tracker RFID '+ticket['identity']
                raw = self._find(client, 'spool', marker)
                if ticket['link']:
                    if raw is None or raw['id'] != ticket['link']['remote_id']:
                        raise AccountingConflict('Spoolman RFID marker changed')
                if raw is None:
                    tag, config = ticket['tag'], ticket['config']
                    if not ticket['can_create']:
                        raise AccountingConflict('Automatic creation disabled')
                    if not ticket['approved'] and tag['format'] != 'bambu' and tag['identity'] not in config.get('confirmed_new_tags', []):
                        raise AccountingConflict('Confirm a new roll or pair this tag with its other side')
                    names = resolve_names(tag, config)
                    material, manufacturer = names['material'], names['manufacturer']
                    if not material or not tag['color'] or manufacturer in ('QIDI-compatible','Unknown','TigerTag'):
                        raise AccountingConflict('Unmapped RFID codes require identified material and color')
                    nominal = tag['nominal_weight_g'] or config.get('nominal_weights', {}).get(tag['material_id'])
                    diameter = tag['diameter_mm'] or config.get('diameters', {}).get(tag['material_id'])
                    initial = config.get('initial_balances', {}).get(tag['identity'])
                    if initial is None and config.get('new_spools') == 'nominal':
                        initial = nominal
                    if initial is None:
                        raise AccountingConflict('Initial remaining mass required for unknown roll')
                    densities = config.get('densities', {})
                    density = next((densities[k] for k in (tag['material_id'], tag['name']) if k in densities), None)
                    if density is None:
                        raise AccountingConflict('Material density is not on the tag; configure a verified value')
                    if nominal is None or diameter is None:
                        raise AccountingConflict('Nominal mass and diameter are not on this tag; configure material properties')
                    display_name = material if tag['format']=='tigertag' and tag['material'] is None else tag['name']
                    fbody = dict(name=(manufacturer+' '+display_name+' '+ '/'.join(tag['colors']))[:64],
                                 material=material, density=density, diameter=diameter,
                                 weight=nominal, color_hex=tag['color'])
                    if len(tag['colors']) > 1:
                        fbody.pop('color_hex')
                        fbody.update(multi_color_hexes=','.join(tag['colors']), multi_color_direction='coaxial')
                    fmarker = 'Tracker RFID material '+revision(fbody)
                    filament = self._find(client, 'filament', fmarker)
                    if filament is None:
                        filament = self._create(ticket, client, 'filament', fmarker, fbody)
                    raw = self._create(ticket, client, 'spool', marker,
                                       dict(filament_id=filament['id'], initial_weight=nominal, remaining_weight=initial))
            except (OSError, TimeoutError):
                if ticket['sid']:
                    return self.owner.call('rfid_commit', ticket)
                raise
            return self.owner.call('rfid_commit', ticket, raw)

    def tick(self):
        for pid, snapshot in self.owner.fleet.snapshot().items():
            for channel, observed in snapshot.get('channels', {}).items():
                if observed.get('state') == 'present' and observed.get('tag'):
                    try: self.results[(pid, channel)] = self.scan(pid, channel)
                    except Exception as exc: self.results[(pid, channel)] = dict(state='held', reason=str(exc))
        from tracker_uid_sender import Sender
        for url in self.allowed_urls:
            pending = self.owner.call('rfid_approve_usage', url)
            if pending and not self.stop_event.is_set():
                Sender(self.owner, [url], client_factory=self.client_factory).send_one(**dict(
                    operation_id=pending[0]['operation_id'], expected_revision=pending[0]['revision']))
        return dict(self.results)

    def start(self):
        if self.thread is not None: raise RuntimeError('RFID worker already started')
        def run():
            while not self.stop_event.is_set():
                self.tick()
                self.stop_event.wait(self.interval)
        self.thread = threading.Thread(target=run, name='tracker-rfid')
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread: self.thread.join()
