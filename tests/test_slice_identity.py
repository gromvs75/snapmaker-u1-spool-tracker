import os
from pathlib import Path
import zipfile

import pytest
from dev.observer_fixture import payload
from slice_identity import bed_identity
from tracker_uid_forecast import SliceForecast, forecast_entry
from tracker_uid_session import Session


def metadata(*pairs):
    return ('<config>' + ''.join(f'<plate><metadata key="plater_id" value="{n}"/>'
            f'<metadata key="gcode_file" value="{p}"/></plate>' for n,p in pairs) + '</config>').encode()


def put(root, number, suffix=47):
    path=root/'project'/'Metadata'/f'.800.{suffix}.gcode'
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(payload())
    config=path.parent/'model_settings.config'
    config.write_bytes(metadata((number,'Metadata/'+path.name)))
    return path,config


@pytest.mark.parametrize('number',[1,2,3])
def test_only_sliced_bed_keeps_real_number(tmp_path,number):
    path,config=put(tmp_path,number)
    assert bed_identity(path,path.stat().st_mtime_ns)==number
    # Finding only this file must not turn bed 2/3 into bed 1.
    session=Session(tmp_path/'db',allowed_urls=[])
    try:
        f=SliceForecast(session,tmp_path);f.poll();f.observer.settle=0
        e=f.poll()['entries'][0]
        assert e['plate']==number
        assert not session.connected and session.call('inspect')['debits']==[]
    finally:session.close()


def test_counter_three_four_can_mean_beds_one_two(tmp_path):
    p,c=put(tmp_path,1,2);q=p.with_name('.800.3.gcode');q.write_bytes(payload())
    c.write_bytes(metadata((1,'Metadata/'+p.name),(2,'Metadata/'+q.name)))
    assert bed_identity(p,p.stat().st_mtime_ns)==1
    assert bed_identity(q,q.stat().st_mtime_ns)==2
    p.unlink()
    assert bed_identity(q,q.stat().st_mtime_ns)==2
    # Explicit new project ordering changes identities, not the file counter.
    c.write_bytes(metadata((3,'Metadata/'+q.name)))
    assert bed_identity(q,q.stat().st_mtime_ns)==3


def test_missing_old_foreign_ambiguous_and_malformed_metadata_are_unknown(tmp_path):
    p,c=put(tmp_path,3);stamp=p.stat().st_mtime_ns
    c.unlink();assert bed_identity(p,stamp) is None
    c.write_bytes(metadata((3,'Metadata/'+p.name)))
    os.utime(c,ns=(stamp-1,stamp-1));assert bed_identity(p,stamp) is None
    c.write_bytes(metadata((3,'other/Metadata/'+p.name)));assert bed_identity(p,stamp) is None
    c.write_bytes(metadata((3,'Metadata/'+p.name),(1,'Metadata/'+p.name)))
    assert bed_identity(p,stamp) is None
    c.write_bytes(b'<config>');assert bed_identity(p,stamp) is None
    c.write_bytes(b'<!DOCTYPE config [<!ENTITY x "3">]><config/>');assert bed_identity(p,stamp) is None
    assert forecast_entry(dict(source='p/Metadata/.800.99.gcode',state='pending'),[],5)['plate'] is None


@pytest.mark.parametrize('archive_name',['.800.51_config.3mf','.3mf'])
def test_config_archive_and_conflicting_sources(tmp_path,archive_name):
    p,c=put(tmp_path,2);xml=c.read_bytes();c.unlink()
    archive=(p.parent if archive_name.endswith('_config.3mf') else p.parent.parent)/archive_name
    with zipfile.ZipFile(archive,'w') as z:z.writestr('Metadata/model_settings.config',xml)
    assert bed_identity(p,p.stat().st_mtime_ns)==2
    c.write_bytes(metadata((1,'Metadata/'+p.name)))
    assert bed_identity(p,p.stat().st_mtime_ns) is None


def test_links_and_oversized_metadata_do_not_escape_project(tmp_path):
    p,c=put(tmp_path,2);other=tmp_path/'outside.config';c.rename(other);c.symlink_to(other)
    assert bed_identity(p,p.stat().st_mtime_ns) is None
    c.unlink();c.write_bytes(b' '*(2*1024*1024+1))
    assert bed_identity(p,p.stat().st_mtime_ns) is None
