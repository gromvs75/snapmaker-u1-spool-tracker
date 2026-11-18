"""Package the guarded UID loader for an offline rehearsal on a prepared U1 model."""
import argparse
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dev.labs.uid_boot_bench.debug_loader import export_kit


def build(destination):
    with TemporaryDirectory() as temp:
        kit = Path(temp) / 'kit'
        export_kit(kit)
        with ZipFile(destination, 'x', compression=ZIP_DEFLATED) as archive:
            for path in sorted(kit.rglob('*')):
                if path.is_file():
                    archive.write(path, path.relative_to(kit))
            archive.write(ROOT / 'docs/development/rfid-package-rehearsal-2026-11-18.md',
                          'README.md')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    build(parser.parse_args().destination)
