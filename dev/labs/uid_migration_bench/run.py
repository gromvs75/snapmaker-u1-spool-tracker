"""Reproducible synthetic migration proof. Does not locate user databases."""
from pathlib import Path
import sys, json, tempfile
REPO=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(REPO/'src'),str(REPO),str(Path(__file__).parent)]
from legacy_storage_fixture import empty_db, validate_db
from tracker_uid_migration import BenchMigration
from tracker_uid_catalog import UidCatalog
from tracker_uid_accounting import UidAccounting, AccountingConflict


def main():
    output=REPO/'output/uid-migration-bench';output.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='proof-',dir=output))
    (root/'.tracker-migration-bench').write_text('synthetic-only')
    (root/'legacy').mkdir()
    data=empty_db();data['printer'].update(host='bench.local',enabled=True)
    data['spools']={'old-id':{'name':'Synthetic PLA','material':'PLA','remaining_g':470.0},
                    'untagged-id':{'name':'Manual PETG','material':'PETG','remaining_g':123.456}}
    data['slots'].update({'1':'old-id','2':'untagged-id'})
    data['plans']['plan']={'filename':'fixture.gcode','sha256':'a'*64,'size':100,'weights':[30,0,0,0],
       'spool_ids':['old-id','','',''],'created_at':900,'status':'committed','printer':data['printer']}
    data['runs']['old-key']={'job_id':'old-job','plan_id':'plan','start_time':1000.0,'filename':'fixture.gcode',
       'status':'committed','terminal_status':'cancelled','accounting_method':'motion_estimate',
       'motion_consumption':{'old-id':30},'motion_capture_id':'old-capture','motion_epoch':'old-epoch'}
    raw=json.dumps(data,ensure_ascii=False,indent=2).encode()
    source=root/'legacy/spools_u1.json';source.write_bytes(raw)
    migration=BenchMigration(root,validator=validate_db)
    receipt=migration.migrate({'bench.local:7125':'stable-a'},{'old-id':'04112233'})
    cat=UidCatalog(migration.target)
    try:
        accounting=UidAccounting(cat)
        fence=accounting.legacy_history('stable-a','old-job',1000)
        assert fence['status']=='committed'
        assert cat.spool('04112233')['remaining_mg']==470000
        assert cat.db.execute('SELECT count(*) FROM uid_debits').fetchone()[0]==0
        assert cat.db.execute('SELECT count(*) FROM legacy_spools').fetchone()[0]==2
        assert json.loads(cat.db.execute('SELECT payload FROM legacy_plans').fetchone()[0])==data['plans']['plan']
    finally:cat.close()
    migration.restore_legacy()
    assert source.read_bytes()==raw
    result={'completed':True,'root':str(root),'receipt':receipt,'backup_exact':migration.backup.read_bytes()==raw,
            'restoration_exact':True,'history_fenced':True,'new_debits':0,'restored_target_disabled':True}
    try:UidCatalog(migration.target)
    except ValueError:pass
    else:raise AssertionError('Restored target must stay disabled')
    (output/'results.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
