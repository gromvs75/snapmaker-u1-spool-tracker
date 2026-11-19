import copy
import gzip
import json

import pytest
import tracker_spoolmandb as db
from test_rfid_enrollment import enrollment, decoded, preview, values, URL
from tracker_rfid import RfidWorker


def row(**kw):
    return dict(id='example',manufacturer='Creality',name='PLA Blue',material='PLA',
                density=1.24,diameter=1.75,weight=1000,color_hex='0000FF',**kw)


def match(catalog, **kw):
    tag=decoded('creality');tag.update(kw)
    return catalog.match(tag,dict(manufacturer='Creality',material='PLA'))


def test_full_snapshot_integrity_and_candidates():
    manifest=json.loads((db.DATA/'manifest.json').read_text())
    rows=json.loads(gzip.decompress((db.DATA/'filaments.json.gz').read_bytes()))
    assert manifest['products']==len(rows)==10058
    catalog=db.bundled()
    r=next(r for r in rows if r['manufacturer']=='Bambu Lab' and r['color_hex']=='FFFFFF' and r['material']=='PLA')
    result=catalog.match(dict(colors=['FFFFFF'],diameter_mm=r['diameter'],nominal_weight_g=r['weight'],name=r['name']),r)
    assert r['id'] in [r['id'] for r in result['candidates']]
    assert result['requires_confirmation'] and result['source']=='SpoolmanDB'


def test_no_uid_guessing_no_fuzzy_color_and_no_ambiguous_defaults():
    first=row();second=dict(first,id='other',name='Another product',density=1.30)
    catalog=db.Catalog([first,second],'f'*64)
    assert match(catalog)['status']=='ambiguous'
    assert match(catalog,name=first['name'])['candidates']==[dict((k,first.get(k)) for k in db.FIELDS)]
    assert match(catalog,colors=['0000FE'])['status']=='not_found'
    assert match(catalog,diameter_mm=2.85)['status']=='not_found'
    assert match(catalog,uid='AABBCCDD')==match(catalog,uid='11223344')
    # Do not silently drop alpha from catalog colors.
    assert match(db.Catalog([dict(first,color_hex='FF0000FF')],'f'*64))['status']=='not_found'


def test_defaults_confirm_two_sides_restore_and_missing_catalog(enrollment,monkeypatch):
    service,owner,fleet,server,path=enrollment
    monkeypatch.setattr(db,'bundled',lambda:db.Catalog([row()],'a'*64))
    fleet.set(decoded('creality'));p=preview(service,fleet)
    assert p['product_lookup']['status']=='suggested'
    assert p['defaults']==dict(remaining_g=None,density=1.24,diameter=1.75,nominal=1000)
    assert not server.posts
    first=service.confirm(p['review_id'],'new',confirmed=True,values=values(p))
    approval=owner.call('settings')['values']['rfid']['approvals'][decoded('creality')['identity']]
    assert approval['catalog']['product_id']=='example'
    package=owner.call('backup_package')
    assert owner.call('validate_backup',package=package)
    server.rows['spool'][0]['remaining_weight']=623.5
    worker=RfidWorker(owner,[URL],client_factory=server,interactive=True)
    worker.scan('a','0')
    fleet.set(decoded('creality',1));p=preview(service,fleet)
    service.confirm(p['review_id'],'pair',confirmed=True,spool_id=first['spool_id'])
    def unavailable():raise FileNotFoundError('offline snapshot absent')
    monkeypatch.setattr(db,'bundled',unavailable)
    assert db.suggest(decoded('creality'),{})['status']=='unavailable'
    for side in (0,1,0):
        fleet.set(decoded('creality',side))
        result=worker.scan('a','0')
        assert result['spool_id']==first['spool_id'] and result['remaining_mg']==623500
    assert server.posts.count('spool')==1 and not server.puts


def test_ambiguous_snapshot_keeps_manual_parameters(enrollment,monkeypatch):
    service,owner,fleet,server,path=enrollment
    first=row();second=dict(first,id='other',name='Other',density=1.30)
    monkeypatch.setattr(db,'bundled',lambda:db.Catalog([first,second],'b'*64))
    fleet.set(decoded('creality'));p=preview(service,fleet)
    assert p['product_lookup']['status']=='ambiguous' and p['defaults']['density'] is None
    result=service.confirm(p['review_id'],'new',confirmed=True,values=values(p))
    assert result['remaining_mg']==840123
    assert 'catalog' not in owner.call('settings')['values']['rfid']['approvals'][decoded('creality')['identity']]


@pytest.mark.parametrize('field,value',[('density',float('nan')),('weight',-1),('diameter',0),('color_hex','bogus')])
def test_invalid_snapshot_rejected(field,value):
    with pytest.raises(ValueError):db.Catalog([dict(row(),**{field:value})],'c'*64)
