"""Record the exact source and SHA256 for a prepared desktop artifact."""
import argparse
import hashlib
import json
import platform
import subprocess
from pathlib import Path


def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('artifact', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    info = {
        'version': '1.3.3rc3',
        'commit': git('rev-parse', 'HEAD'),
        'tree': git('rev-parse', 'HEAD^{tree}'),
        'dirty': bool(git('status', '--porcelain', '--untracked-files=no')),
        'platform': platform.system(),
        'architecture': platform.machine(),
        'python': platform.python_version(),
        'artifact': args.artifact.name,
        'sha256': hashlib.sha256(args.artifact.read_bytes()).hexdigest(),
        'windows_gui_verified': False,
    }
    args.output.write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
