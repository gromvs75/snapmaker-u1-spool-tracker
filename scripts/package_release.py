"""Assemble a desktop distribution with guides and attribution."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.3.2'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('platform', choices=['macOS', 'Windows'])
    parser.add_argument('application', type=Path)
    args = parser.parse_args()
    application = args.application.resolve(strict=True)
    name = f'SnapmakerSpoolTracker-{VERSION}-{args.platform}'
    stage = ROOT / 'build' / 'distribution' / name
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    destination = stage / application.name
    if application.is_dir():
        # Preserve bundle symlinks, permissions and signature.
        subprocess.run(['ditto', str(application), str(destination)], check=True)
    else:
        shutil.copy2(application, destination)
    shutil.copy2(ROOT / 'LICENSE', stage / 'LICENSE.txt')
    shutil.copytree(ROOT / 'docs' / 'licenses', stage / 'licenses')
    (stage / 'guides').mkdir()
    for language in ('ru', 'en'):
        shutil.copy2(ROOT / 'docs' / 'guides' / f'spoolman-{language}.md', stage / 'guides')
        shutil.copy2(ROOT / 'docs' / 'guides' / f'{language}.md', stage / 'guides')
    notes = (ROOT / 'docs' / 'releases' / f'{VERSION}.md').read_text(encoding='utf-8')
    (stage / 'RELEASE-NOTES.md').write_text(notes.replace('../guides/', 'guides/').replace('../licenses/', 'licenses/'), encoding='utf-8')
    (stage / 'START-HERE.txt').write_text(
        'Tracker 1.3.2 — cancelled-print accounting fix.\n'
        'Stock U1 firmware; Spoolman is installed separately.\n'
        'Read guides/spoolman-ru.md or guides/spoolman-en.md before connecting.\n'
        'Export your installed Tracker backup before upgrading.\n'
        'This build uses the existing 1.2 beta / 1.2.1 inventory directory.\n'
        'Do not run two instances accounting for the same printer.\n'
        'Spoolman: start read-only; leave printer monitoring and usage sending off for the first check.\n'
        'Windows GUI and real Snorca slicing on Windows remain UNVERIFIED.\n'
        'macOS: Apple Silicon; ad-hoc signature, not notarized.\n', encoding='utf-8')
    archive = application.parent / (name + '.zip')
    if args.platform == 'macOS':
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(stage), str(archive)], check=True)
    else:
        shutil.make_archive(str(archive.with_suffix('')), 'zip', stage.parent, stage.name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n', encoding='utf-8')
    print(archive)


if __name__ == '__main__':
    main()
