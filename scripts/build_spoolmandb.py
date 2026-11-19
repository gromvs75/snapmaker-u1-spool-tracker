"""Validate and vendor a reviewed public snapshot; no runtime network dependency."""
import argparse
import datetime
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tracker_spoolmandb import validate


def build(source, license_path, destination):
    rows = validate(json.loads(source.read_bytes()))
    raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'filaments.json.gz').write_bytes(gzip.compress(raw, mtime=0))
    (destination / 'LICENSE').write_bytes(license_path.read_bytes())
    manifest = dict(source='https://donkie.github.io/SpoolmanDB/filaments.json',
                    captured_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    sha256=hashlib.sha256(raw).hexdigest(), products=len(rows), license='MIT')
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('license', type=Path)
    parser.add_argument('--destination', type=Path, default=ROOT / 'src/tracker_spoolmandb_data')
    args = parser.parse_args()
    build(args.source, args.license, args.destination)
