"""Create a separate Snorca project with the bed comment; never edit the input.

No slicer launch, profile installation, network access or G-code execution.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from slice_bed_marker import PROFILE_COMMENT

CONFIG = 'Metadata/project_settings.config'


def prepare(source, target):
    source, target = Path(source), Path(target)
    if source.resolve() == target.resolve() or target.exists():
        raise ValueError('Output must be a new, separate file')
    with zipfile.ZipFile(source) as archive:
        members = archive.infolist()
        if len(members) > 4096 or len({m.filename for m in members}) != len(members):
            raise ValueError('Ambiguous project archive')
        info = archive.getinfo(CONFIG)
        if info.file_size > 4*1024*1024 or sum(m.file_size for m in members) > 512*1024*1024:
            raise ValueError('Project is too large')
        config = json.loads(archive.read(CONFIG))
        start = config.get('machine_start_gcode')
        if not isinstance(start, str) or not start.strip():
            raise ValueError('Explicit machine_start_gcode required')
        if 'TRACKER_BED_' in start:
            if [line for line in start.splitlines() if 'TRACKER_BED_' in line] != [PROFILE_COMMENT]:
                raise ValueError('Existing bed marker needs review')
        else:
            config['machine_start_gcode'] = PROFILE_COMMENT+'\n'+start
        # No paths from the archive are extracted into the filesystem.
        with tempfile.TemporaryFile() as pending:
            with zipfile.ZipFile(pending, 'w') as result:
                for member in members:
                    if member.filename == CONFIG:
                        result.writestr(member, json.dumps(config, ensure_ascii=False, indent=2).encode())
                    else:
                        with archive.open(member) as reader, result.open(member, 'w') as writer:
                            shutil.copyfileobj(reader, writer)
            pending.seek(0)
            with target.open('xb') as output:
                shutil.copyfileobj(pending, output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    args = parser.parse_args()
    prepare(args.source, args.target)
