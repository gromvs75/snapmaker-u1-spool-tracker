"""Build the offline U1 trial kit with explicit scope and file hashes."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]


def build(path):
    files={name:(ROOT/source).read_bytes() for name,source in {
        'rfid_u1_trial.py':'scripts/rfid_u1_trial.py',
        'tracker_uid.py':'dev/klipper/tracker_uid.py',
        'README-RU.md':'docs/guides/rfid-u1-trial-0.7-ru.md',
        'LICENSE':'LICENSE',
    }.items()}
    manifest=dict(version='0.7.0-trial',scope='offline U1 filesystem; no live root or service control',
                  module_version='0.8.0-roll-identity-bench',
                  files={n:hashlib.sha256(raw).hexdigest() for n,raw in files.items()})
    path.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(path,'x',ZIP_DEFLATED) as archive:
        for name,raw in files.items():archive.writestr(name,raw)
        archive.writestr('manifest.json',json.dumps(manifest,indent=2))
    with ZipFile(path) as archive:
        assert archive.testzip() is None
        for name,digest in manifest['files'].items():assert hashlib.sha256(archive.read(name)).hexdigest()==digest
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix('.zip.sha256').write_text(digest+'  '+path.name+'\n')
    print(json.dumps(dict(archive=str(path),sha256=digest,manifest=manifest),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('destination',type=Path)
    build(parser.parse_args().destination)
