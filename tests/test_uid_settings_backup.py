import base64
import copy
import hashlib
import json
import sqlite3
import pytest
from tracker_uid_session import Session
from tracker_uid_settings import validate_printers
from tracker_uid_sender import Sender


class Fleet:
    def __init__(self,endpoints):self.endpoints=endpoints;self.started=False
    def start(self):self.started=True
    def stop(self):self.started=False
    def snapshot(self):return {e.printer_id:dict(printer_id=e.printer_id,name=e.name,state='ready' if self.started else 'stopped',client_session='test',generation=1,epoch='test',channels={str(i):dict(state='absent',uid=None) for i in range(4)}) for e in self.endpoints}


@pytest.fixture
def app(tmp_path):
    s=Session(tmp_path,fleet_factory=Fleet)
    yield s
    s.close()


def configure(s):
    settings=s.call('settings')
    return s.call('save_settings',values={'printers':[dict(id=p,name=p,url=f'http://127.0.0.1:{7125+i}') for i,p in enumerate(('a','b'))]},expected_revision=settings['revision'])


def test_connect_save_restart_and_identity(app,tmp_path):
    configured=configure(app)
    app.call('connect_printers',confirmed=True)
    assert set(app.fleet.snapshot())=={'a','b'}
    with pytest.raises(ValueError):app.call('save_settings',values=configured['values'],expected_revision=configured['revision'])
    app.call('disconnect_printers',confirmed=True)
    configured['values']['printers'][0]['name']='Renamed'
    app.call('save_settings',values=configured['values'],expected_revision=configured['revision'])
    app.close()
    other=Session(tmp_path,fleet_factory=Fleet)
    try:
        assert not other.connected
        assert other.fleet.snapshot()['a']['name']=='Renamed'
    finally:other.close()


@pytest.mark.parametrize('printers',[[dict(id='a',name='a',url='file:///tmp/x')],[dict(id='a',name='a',url='http://u:p@localhost')],[dict(id='a',name='a',url='http://localhost:99999')],[dict(id='a',name='a',url='http://localhost'),dict(id='b',name='b',url='http://LOCALHOST:80/')]])
def test_invalid_endpoints(printers):
    with pytest.raises(ValueError):validate_printers(printers)


def test_stale_settings_and_id_removal_rejected(app):
    old=app.call('settings');configure(app)
    with pytest.raises(ValueError):app.call('save_settings',values={'printer_names':{'a':'x'}},expected_revision=old['revision'])
    with pytest.raises(ValueError):app.call('save_settings',values={'printers':[]},expected_revision=app.call('settings')['revision'])


def test_restore_roundtrip_preserves_uid_and_requires_confirmation(app):
    configure(app);app.call('register','04112233','RFID',123456)
    app.call('register_manual','Manual',500000,spool_id='manual')
    app.call('connect_printers',confirmed=True)
    app.call('assign_manual','a','0','manual',confirmed=True)
    package=app.call('backup_package')
    with pytest.raises(ValueError):app.call('validate_backup',package=package)
    app.call('disconnect_printers',confirmed=True)
    app.call('register_manual','Added later',1000)
    preview=app.call('validate_backup',package=package)
    with pytest.raises(ValueError):app.call('restore_backup',package=package,expected_revision=preview['current_revision'])
    result=app.call('restore_backup',package=package,expected_revision=preview['current_revision'],confirmed=True)
    state=app.call('inspect');assert len(state['spools'])==2
    assert any(s['uid']=='04112233' and s['remaining_mg']==123456 for s in state['spools'])
    assert not state['manual_assignments'][0]['confirmed'] and not app.connected
    rollback=json.loads((app.directory/result['rollback_file']).read_text())
    assert app.call('validate_backup',package=rollback)['spools']==3


def test_checksum_schema_and_foreign_keys_checked_before_changes(app,tmp_path):
    configure(app);package=app.call('backup_package');before=app.call('inspect')
    corrupt=copy.deepcopy(package);corrupt['sha256']='0'*64
    with pytest.raises(ValueError):app.call('validate_backup',package=corrupt)
    path=tmp_path/'bad.sqlite';path.write_bytes(base64.b64decode(package['base64']))
    db=sqlite3.connect(path);db.execute("INSERT INTO spool_details VALUES('missing','{}')");db.commit();db.close()
    raw=path.read_bytes();bad=dict(package,base64=base64.b64encode(raw).decode(),sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError):app.call('validate_backup',package=bad)
    db=sqlite3.connect(path);db.execute('DELETE FROM spool_details');db.execute('CREATE TABLE future(x)');db.commit();db.close()
    raw=path.read_bytes();bad.update(base64=base64.b64encode(raw).decode(),sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError):app.call('validate_backup',package=bad)
    assert app.call('inspect')==before


def test_restore_rejects_intervening_write(app):
    package=app.call('backup_package');preview=app.call('validate_backup',package=package)
    app.call('register_manual','New',1000)
    with pytest.raises(ValueError):app.call('restore_backup',package=package,expected_revision=preview['current_revision'],confirmed=True)
    assert len(app.call('inspect')['spools'])==1
    assert not list(app.directory.glob('before-restore-*'))


def test_restore_quarantines_old_pending_and_removes_unlock(app,tmp_path):
    package=app.call('backup_package');path=tmp_path/'seed.sqlite';path.write_bytes(base64.b64decode(package['base64']))
    db=sqlite3.connect(path)
    db.execute("INSERT INTO uid_remote_outbox VALUES('old',1,'old','http://127.0.0.1:18899',1,298,'pending')")
    db.commit();db.close();raw=path.read_bytes()
    package.update(base64=base64.b64encode(raw).decode(),sha256=hashlib.sha256(raw).hexdigest())
    preview=app.call('validate_backup',package=package)
    app.call('restore_backup',package=package,expected_revision=preview['current_revision'],confirmed=True)
    assert app.call('delivery_list')[0]['state']=='uncertain'
    class NoNetwork:
        def __init__(self,*a):raise AssertionError('No retry allowed')
    assert Sender(app,['http://127.0.0.1:18899'],client_factory=NoNetwork).send_one()=='blocked'
