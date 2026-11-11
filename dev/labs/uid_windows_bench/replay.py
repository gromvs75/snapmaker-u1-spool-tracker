"""Nonzero accounting replay exercised by the frozen executable itself."""
import time
from tracker_uid_runtime import AccountingOwner
from tracker_uid_catalog import UidCatalog
from dev.labs.uid_gui_bench.run import Fleet


def verify(path):
    fleet = Fleet()
    owner = AccountingOwner(path, fleet)
    histories = {}
    evidence = {}
    try:
        for pid, head in [('a', 0), ('b', 1)]:
            sid = 'ci-' + pid
            owner.call('register_manual', sid, 500000, spool_id=sid, details={'material': 'PLA'})
            owner.call('assign_manual', pid, str(head), sid, confirmed=True)
            start = owner.call('inventory_snapshot', pid)
            ev = dict(complete=True, continuous=True, capture_id='capture-'+pid, epoch='ci',
                      terminal_state='cancelled', start=start,
                      comparison={'matches': True, 'printer_total_mm': 100},
                      feed={'valid': True, 'covered': [True]*4, 'insertions': [False]*4},
                      tags={'known': True, 'unchanged': [True]*4},
                      heads=[{'head': i, 'net_mm': 100 if i == head else 0} for i in range(4)],
                      profile={'filename': pid+'.gcode', 'started_at': 1000.0,
                               'mapping': [0,1,2,3], 'logical_weights': [1,1,1,1], 'filament_type': 'PLA;PLA;PLA;PLA',
                               'parameters': [{'diameter_mm': 1.75, 'density_g_cm3': 1.24} for _ in range(4)]})
            evidence[pid] = ev
            histories[pid] = dict(job_id='same-id', start_time=1000.0, filename=pid+'.gcode', status='cancelled')
            assert owner.call('start', pid, filename=pid+'.gcode', observed_at=1000.0,
                              capture_id=ev['capture_id'], epoch='ci', start=start, channels=[str(head)])['status']=='started'
            assert owner.call('terminal', pid, ev)['status']=='pending'
            assert owner.call('history', pid, [histories[pid]])[0]['status']=='applied'
        for _ in range(10):
            for pid in histories:
                assert owner.call('history', pid, [histories[pid]])[0]['status']=='duplicate'
        owner.call('disconnected', 'a')
        owner.close()
        owner = AccountingOwner(path, fleet)
        for pid in histories:
            assert owner.call('history', pid, [histories[pid]])[0]['status']=='duplicate'
        before = owner.call('inspect')
        assert len(before['debits']) == 2
        assert sorted(s['remaining_mg'] for s in before['spools']) == [499702, 499702]
        # A later interrupted capture receives a durable resolution fence.
        owner.call('assign_manual', 'a', '0', 'ci-a', confirmed=True)
        ev = dict(evidence['a'], capture_id='interrupted', start=owner.call('inventory_snapshot','a'))
        ev['profile'] = dict(ev['profile'], started_at=2000.0)
        key = owner.call('start','a',filename='a.gcode',observed_at=2000.0,
                         capture_id='interrupted',epoch='ci',start=ev['start'],channels=['0'])['job_key']
        owner.call('disconnected','a')
        job = next(j for j in owner.call('inspect')['jobs'] if j['job_key']==key)
        owner.call('resolve_interrupted',key,job['resolution_version'],
                   {'state':'cancelled','checked_at':time.monotonic(),
                    'connection_token':UidCatalog.connection_token(fleet.snapshot()['a'])},
                   confirmed=True,accept_unaccounted=True,mode='15_minutes')
        assert owner.call('terminal','a',ev)['status']=='resolved_without_debit'
        late = dict(histories['a'],job_id='late',start_time=2000.0)
        for _ in range(5):
            assert owner.call('history','a',[late])[0]['status']=='resolved_without_debit'
        owner.close()
        owner = AccountingOwner(path,fleet)
        assert owner.call('history','a',[late])[0]['status']=='resolved_without_debit'
        after = owner.call('inspect')
        assert len(after['debits'])==2 and len(after['resolutions'])==1
        assert sorted(s['remaining_mg'] for s in after['spools'])==[499702,499702]
        return {'passed':True,'debit_count':2,'total_mg':596,'balances_mg':[499702,499702],
                'duplicate_history_batches':22,'late_history_batches':6,'state':after}
    finally:
        owner.close()
