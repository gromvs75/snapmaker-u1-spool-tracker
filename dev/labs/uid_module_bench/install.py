"""Compatibility import for existing benches; deployment logic lives in scripts."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from rfid_module_tool import Installer, MARKER, BLOCK, CONFIG, MODULE, atomic

if __name__ == '__main__':
    from rfid_module_tool import main
    raise SystemExit(main())
