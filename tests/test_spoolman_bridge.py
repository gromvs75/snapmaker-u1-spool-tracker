import copy
import json
import time
import pytest
from spoolman_bridge import Bridge, Client, endpoint, unavailable, remote_id, blank, book
from storage import Store, StorageError
from accounting import create_plan, apply_history_job, fingerprint_file
from backup import create_backup, import_backup
from forecast import forecast_entry

URL = 'http://127.0.0.1:7912'

class Fake:
    def __init__(self):
        self.used = 0
        self.writes = 0
        self.fail = False
        self.lost = False
        self.archived = False

    def row(self):
        return {'id': 1, 'remaining_weight': 1000-self.used, 'archived': self.archived,
                'filament': {'name': 'White', 'material': 'PLA', 'color_hex': 'ffffff'}}

    def catalog(self):
        if self.fail: raise OSError('offline')
        from spoolman_bridge import catalog_item
        return {'1': catalog_item(self.row())}

    def request(self, method, path, body=None):
        if self.fail: raise OSError('offline')
        if method == 'PUT':
            self.used += body['use_weight']; self.writes += 1
            if self.lost: raise OSError('response lost')
        return self.row(), {}


def setup(tmp_path, mode='send'):
    store = Store(tmp_path / 'inventory'); fake = Fake()
    bridge = Bridge(store, lambda url: fake)
    bridge.configure(URL, mode, True); bridge.attach(1, 0)
    return store, fake, bridge, remote_id(URL, 1)


def complete(store, tmp_path, start=1000):
    def enable(db): db['printer']['enabled'] = True
    store.update(enable)
    file = tmp_path / 'part.gcode'; file.write_text('test')
    create_plan(store, file, file.name, [20,0,0,0], store.read(), now=start-1)
    printer = store.read()['printer']
    job = {'job_id': str(start), 'filename': file.name, 'status': 'in_progress', 'start_time': start}
    apply_history_job(store, printer, job, remote_fingerprint=fingerprint_file(file), mapping_evidence={'mapping':[0,1,2,3], 'auto_replenish':False})
    job['status'] = 'completed'
    apply_history_job(store, printer, job)
    return printer, job


def ops(store): return store.read()['spoolman']['outbox']


def test_completed_print_queues_exact_amount_without_local_debit(tmp_path):
    store, fake, bridge, sid = setup(tmp_path)
    printer, job = complete(store, tmp_path)
    assert store.read()['spools'][sid]['remaining_g'] == 1000
    assert len(ops(store)) == 1
    assert next(iter(ops(store).values()))['grams'] == 20
    apply_history_job(store, printer, job)
    assert len(ops(store)) == 1
    bridge.send_one(); bridge.send_one()
    assert fake.writes == 1 and fake.used == 20
    assert store.read()['spools'][sid]['remaining_g'] == 980
    assert next(iter(ops(store).values()))['state'] == 'sent'


def test_read_only_never_writes_or_changes_cached_balance(tmp_path):
    store, fake, bridge, sid = setup(tmp_path, 'read'); complete(store,tmp_path)
    bridge.send_one()
    assert fake.writes == 0
    assert next(iter(ops(store).values()))['state'] == 'external'
    assert store.read()['spools'][sid]['remaining_g'] == 1000
    bridge.configure(URL, 'send', True); bridge.send_one()
    assert fake.writes == 0  # old history is not swept into send mode


def test_lost_response_blocks_retries_and_forecast(tmp_path):
    store, fake, bridge, sid = setup(tmp_path); complete(store,tmp_path)
    fake.lost = True; bridge.send_one(); bridge.send_one()
    assert fake.writes == 1 and fake.used == 20
    assert next(iter(ops(store).values()))['state'] == 'uncertain'
    assert unavailable(store.read(), sid)
    bridge.resolve(next(iter(ops(store))), 'applied', 'Verified at server')
    bridge.send_one(); assert fake.writes == 1
    assert not unavailable(store.read(), sid)


def test_explicit_not_applied_requires_note(tmp_path):
    store, fake, bridge, sid = setup(tmp_path); complete(store,tmp_path)
    key = next(iter(ops(store)))
    store.update(lambda db: db['spoolman']['outbox'][key].update(state='sending'))
    bridge.recover()
    with pytest.raises(ValueError): bridge.resolve(key, 'not_applied', '')
    bridge.resolve(key, 'not_applied', 'Server audit confirms not received')
    bridge.send_one(); assert fake.used == 20


def test_offline_before_send_stays_pending(tmp_path):
    store, fake, bridge, sid = setup(tmp_path); complete(store,tmp_path)
    fake.fail = True; bridge.send_one(); bridge.refresh()
    assert fake.writes == 0
    assert next(iter(ops(store).values()))['state'] == 'pending'
    assert unavailable(store.read(), sid)
    fake.fail=False; bridge.send_one(); assert fake.used == 20


def test_freshness_archive_and_missing_block_forecast(tmp_path):
    store, fake, bridge, sid = setup(tmp_path)
    event={'source':'/x/Metadata/plate_1.0.gcode','weights':[10,0,0,0]}
    assert not forecast_entry(event,inventory=store.read())['unknown']
    store.update(lambda db: db['spoolman'].update(checked_at=time.time()-61))
    assert forecast_entry(event,inventory=store.read())['unknown']
    fake.archived=True; bridge.refresh()
    assert unavailable(store.read(),sid)
    store.update(lambda db: db['spoolman'].update(catalog={}))
    assert unavailable(store.read(),sid)


def test_duplicate_assignment_and_server_switch_rejected(tmp_path):
    store, fake, bridge, sid=setup(tmp_path)
    with pytest.raises(ValueError): bridge.attach(1,1)
    with pytest.raises(ValueError): bridge.configure('http://localhost:9000','read')
    bridge.detach(sid); bridge.configure('http://localhost:9000','read')
    assert not store.read()['spools']


def test_pending_blocks_detach_and_mode_switch(tmp_path):
    store,fake,bridge,sid=setup(tmp_path);complete(store,tmp_path)
    with pytest.raises(ValueError):bridge.detach(sid)
    with pytest.raises(ValueError):bridge.configure(URL,'read')


def test_restored_pending_becomes_uncertain_and_disables_sender(tmp_path):
    store,fake,bridge,sid=setup(tmp_path);complete(store,tmp_path)
    backup=tmp_path/'backup.json';backup.write_text(json.dumps(create_backup(store,'test')))
    bridge.send_one();assert fake.used==20
    import_backup(store,backup)
    bridge.send_one()
    assert fake.used==20
    assert store.read()['spoolman']['mode']=='off'
    assert next(iter(ops(store).values()))['state']=='uncertain'


def test_changed_print_context_cannot_charge(tmp_path):
    store,fake,bridge,sid=setup(tmp_path);complete(store,tmp_path)
    key=next(iter(store.read()['runs']))
    def change(db):
        db['spoolman']['epoch']='different'
        book(db,key,{sid:4})
    with pytest.raises(ValueError):store.update(change)
    assert fake.writes==0


def test_reprint_is_separate_operation(tmp_path):
    store,fake,bridge,sid=setup(tmp_path);complete(store,tmp_path,1000);bridge.send_one()
    complete(store,tmp_path,2000);bridge.send_one()
    assert fake.used==40 and len(ops(store))==2


def test_two_workers_cannot_start(tmp_path):
    store,fake,bridge,sid=setup(tmp_path)
    from filelock import Timeout
    bridge.process_lock.acquire()
    try:
        second=Bridge(store,lambda url:fake)
        with pytest.raises(Timeout):second.start()
    finally:bridge.process_lock.release()


@pytest.mark.parametrize('url',['file:///tmp/x','http://u:p@localhost','http://localhost?token=x','http://localhost/api/v1','http://local host',''])
def test_url_rejects_credentials_and_nonserver_addresses(url):
    with pytest.raises(ValueError):endpoint(url)


def test_malformed_outbox_fails_closed(tmp_path):
    store,fake,bridge,sid=setup(tmp_path)
    with pytest.raises(StorageError):store.update(lambda db:db['spoolman']['outbox'].update(bad={'state':'pending'}))


def test_import_cannot_erase_current_pending_operation(tmp_path):
    store,fake,bridge,sid=setup(tmp_path)
    backup=tmp_path/'old.json';backup.write_text(json.dumps(create_backup(store,'test')))
    complete(store,tmp_path)
    with pytest.raises(StorageError,match='Resolve Spoolman'):
        import_backup(store,backup)
    assert len(ops(store))==1


def test_restored_uncertain_can_reconnect_but_does_not_auto_send(tmp_path):
    store,fake,bridge,sid=setup(tmp_path);complete(store,tmp_path)
    backup=tmp_path/'old.json';backup.write_text(json.dumps(create_backup(store,'test')))
    bridge.send_one(); import_backup(store,backup)
    bridge.configure(URL,'send',True); bridge.send_one()
    assert fake.writes==1
    key=next(iter(ops(store)))
    bridge.resolve(key,'applied','Confirmed in Spoolman');bridge.send_one()
    assert fake.writes==1


def test_reattach_preserves_tag_calibration(tmp_path):
    store,fake,bridge,sid=setup(tmp_path)
    store.update(lambda db:db['spools'][sid].update(calibration={'uid':'01020304'}))
    bridge.attach(1,0)
    assert store.read()['spools'][sid]['calibration']['uid']=='01020304'


def test_multiple_pending_jobs_stop_at_first_uncertain(tmp_path):
    store,fake,bridge,sid=setup(tmp_path);complete(store,tmp_path,1000);complete(store,tmp_path,2000)
    fake.lost=True;bridge.send_one();bridge.send_one()
    assert fake.writes==1
    assert sorted(op['state'] for op in ops(store).values())==['pending','uncertain']
