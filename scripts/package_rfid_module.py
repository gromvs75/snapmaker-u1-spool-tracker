"""Produce an offline simulator-only RFID kit; no deployment or network access."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def build(destination):
    destination=Path(destination)
    if destination.exists():raise ValueError('Output exists; preserve previous kit')
    files={'rfid_module_tool.py':ROOT/'scripts/rfid_module_tool.py',
           'tracker_uid.py':ROOT/'dev/klipper/tracker_uid.py',
           'README-RU.md':ROOT/'docs/guides/rfid-module-install-ru.md',
           'README-EN.md':ROOT/'docs/guides/rfid-module-install-en.md'}
    payload={name:path.read_bytes() for name,path in files.items()}
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip())
    manifest=dict(schema=1,kit_version='0.2.0-bench',source_commit=commit,dirty=dirty,
                  scope='marked-stopped-simulators-only',
                  files={name:hashlib.sha256(raw).hexdigest() for name,raw in payload.items()})
    payload['manifest.json']=json.dumps(manifest,indent=2).encode()
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,raw in payload.items():archive.writestr(name,raw)
    digest=hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(destination.suffix+'.sha256').write_text(digest+'  '+destination.name+'\n')
    return dict(path=str(destination.resolve()),sha256=digest,manifest=manifest)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    print(json.dumps(build(parser.parse_args().output),indent=2))
