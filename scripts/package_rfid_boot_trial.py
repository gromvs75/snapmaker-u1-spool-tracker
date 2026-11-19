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
            guide = (ROOT / 'docs/guides/rfid-automatic-lookup-bench-ru.md').read_text()
            archive.writestr('README.md', guide.replace('../development/', 'development/').replace('(rfid-all-formats-bench-ru.md)', '(guides/rfid-all-formats-bench-ru.md)'))
            report = (ROOT / 'docs/development/rfid-automatic-lookup-2026-11-19.md').read_text()
            archive.writestr('development/rfid-automatic-lookup-2026-11-19.md',
                            report.replace('../guides/rfid-automatic-lookup-bench-ru.md', '../README.md'))
            archive.write(ROOT / 'docs/guides/rfid-automatic-lookup-bench-ru.md', 'guides/rfid-automatic-lookup-bench-ru.md')
            archive.write(ROOT / 'docs/guides/rfid-all-formats-bench-ru.md', 'guides/rfid-all-formats-bench-ru.md')
            archive.write(ROOT / 'docs/development/rfid-all-formats-2026-11-19.md', 'development/rfid-all-formats-2026-11-19.md')
            archive.write(ROOT / 'docs/guides/rfid-minimal-bench-ru.md', 'UID-0.2.md')
            archive.write(ROOT / 'docs/guides/rfid-multibrand-bench-ru.md', 'guides/rfid-multibrand-bench-ru.md')
            archive.write(ROOT / 'docs/development/rfid-qidi-anycubic-2026-11-19.md', 'development/rfid-qidi-anycubic-2026-11-19.md')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    build(parser.parse_args().destination)
