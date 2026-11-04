#!/usr/bin/env python3
"""Run Tracker from a source checkout without changing its data settings."""
from pathlib import Path
import sys

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
    from spool_tracker import main
    raise SystemExit(main())
