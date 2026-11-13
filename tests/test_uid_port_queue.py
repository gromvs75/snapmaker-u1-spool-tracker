from concurrent.futures import ThreadPoolExecutor
import base64
import sqlite3
from tracker_uid_runtime import AccountingOwner
from test_uid_accounting import snapshot
from test_uid_motion_adapter import evidence
from test_accounting import setup_plan


def test_two_printers_three_reprints_and_restart_do_not_double_debit(tmp_path):
    store,*_=setup_plan(tmp_path)
    class Fleet:
        def snapshot(self):return {pid:snapshot(pid,{}) for pid in ('a','b')}
    path=tmp_path/'uid.sqlite';owner=AccountingOwner(path,Fleet());history={'a':[],'b':[]}
    try:
        for pid in history:
            owner.call('create_spool',pid,500,details={'material':'PLA'},assignment=dict(printer_id=pid,channel='0',expected_version='',confirmed=True))
        for run in range(3):
            for pid in history:
                e=evidence(store);e['capture_id']=f'{pid}-{run}';e['start']=owner.call('inventory_snapshot',pid)
                started=1010.+run*100
                owner.call('start',pid,filename='same.gcode',observed_at=started,capture_id=e['capture_id'],epoch=e['epoch'],start=e['start'],channels=['0'])
                e['profile'].update(filename='same.gcode',started_at=started)
                # The recorded profile is part of evidence, never force matches=True.
                e['filename']='same.gcode';e['terminal_state']='completed'
                owner.call('terminal',pid,e)
                history[pid].append(dict(job_id=f'{pid}-{run}',start_time=started,filename='same.gcode',status='completed'))
            with ThreadPoolExecutor(2) as pool:
                list(pool.map(lambda pid:owner.call('history',pid,history[pid]),history))
        report=owner.call('inspect')
        assert len(report['debits'])==6, report['reviews']
        assert [s['remaining_mg'] for s in report['spools']]==[499106,499106]
        backup=owner.call('export_backup');dest=tmp_path/'backup.sqlite';dest.write_bytes(base64.b64decode(backup['base64']))
        db=sqlite3.connect(dest)
        try:assert db.execute('SELECT count(*) FROM uid_debits').fetchone()[0]==6
        finally:db.close()
    finally:owner.close()
    owner=AccountingOwner(path,Fleet())
    try:
        for _ in range(3):
            for pid in history:owner.call('history',pid,history[pid])
        assert len(owner.call('inspect')['debits'])==6
    finally:owner.close()
