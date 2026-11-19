"""Package the frozen rc2 module, offline installer and readable recovery guide."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
RC2 = '01cfe7b7503dac3f6b2df4d0c69813e54cac4dd3'


def build(destination, evidence=None):
    payload = {}
    for name, source in {
        'tracker_uid.py': 'dev/klipper/tracker_uid.py',
        'rfid_u1_trial.py': 'scripts/rfid_u1_trial.py',
    }.items():
        raw = (ROOT/source).read_bytes()
        frozen = subprocess.check_output(['git', 'show', RC2+':'+source], cwd=ROOT)
        if raw != frozen:
            raise ValueError('Payload differs from frozen rc2: '+source)
        payload[name] = raw
    guide = (ROOT/'docs/guides/rfid-module-0.8-rc2-ru.md').read_bytes()
    payload.update({'README-RU.md': guide, 'ИНСТРУКЦИЯ-RU.txt': b'\xef\xbb\xbf'+guide,
                    'verify_package.py': (ROOT/'scripts/verify_rfid_package.py').read_bytes(),
                    'LICENSE': (ROOT/'LICENSE').read_bytes()})
    if evidence:
        for path in sorted(evidence.glob('*-VERIFIED.json')):
            json.loads(path.read_text())
            payload[path.name] = path.read_bytes()
    manifest = dict(schema=1, kit_version='0.8.0-rc2-kit', module_version='0.8.0-roll-identity-bench',
        installer_version='0.7.0-trial', tracker_version='2.1.0rc2', tracker_source_commit=RC2,
        status_schema_version=1, scope='offline-u1-only', hardware_verified=False,
        stock_driver_version='2.1.0.157',
        stock_driver_sha256='ce7363f8b512e5474d18bd57cdf0660e6e2df57dc256e22f743b3b28c1b70be8',
        files={n: hashlib.sha256(raw).hexdigest() for n, raw in payload.items()})
    payload['manifest.json'] = json.dumps(manifest, indent=2, ensure_ascii=False).encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, 'x', ZIP_DEFLATED) as bundle:
        for name, raw in payload.items(): bundle.writestr(name, raw)
    with ZipFile(destination) as bundle:
        assert bundle.testzip() is None
        for name, digest in manifest['files'].items():
            assert hashlib.sha256(bundle.read(name)).hexdigest() == digest
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix('.zip.sha256').write_text(digest+'  '+destination.name+'\n')
    print(json.dumps(dict(archive=str(destination), sha256=digest, files=len(payload)), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    build(args.destination, args.evidence)
