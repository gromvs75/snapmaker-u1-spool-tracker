"""Inspect pinned driver snapshots and rehearse installation for approved hashes."""
import argparse
import importlib.util
import json
from pathlib import Path
import tempfile

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('rfid_offline_tool',ROOT/'scripts/rfid_module_tool.py')
tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    drivers=sorted(args.corpus.glob('*/klippy/extras/fm175xx_reader.py'))
    if not drivers:raise ValueError('Pinned driver corpus missing')
    root=Path(tempfile.mkdtemp(prefix='rfid-compatibility-',dir='/private/tmp'))
    results=[]
    for driver in drivers:
        version=driver.parents[2].name;dest=root/version;dest.mkdir()
        (dest/'.tracker-uid-simulator.json').write_text(json.dumps(tool.MARKER))
        for part in ('klipper/klippy/extras','printer_data/config'):(dest/part).mkdir(parents=True)
        raw=driver.read_bytes();(dest/tool.DRIVER).write_bytes(raw)
        before=b'[printer]\nkinematics: none\n';(dest/tool.MAIN).write_bytes(before)
        installer=tool.Installer(dest);report=installer.inspect()
        if report['compatible']:
            plan=installer.plan();installer.install(expected_revision=plan['revision']);installer.rollback()
            assert (dest/tool.DRIVER).read_bytes()==raw and (dest/tool.MAIN).read_bytes()==before
            assert not (dest/tool.TARGETS[0]).exists()
        else:
            try:installer.install()
            except ValueError:pass
            else:raise AssertionError('Unknown driver installed')
            assert not installer.journal.exists() and not (dest/tool.TARGETS[0]).exists()
        results.append(dict(snapshot=version,sha256=tool.sha(raw),result=report))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(results,indent=2))
    print(json.dumps(dict(root=str(root),snapshots=len(results),compatible=sum(r['result']['compatible'] for r in results))))


if __name__=='__main__':main()
