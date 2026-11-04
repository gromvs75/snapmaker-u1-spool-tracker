#!/bin/bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/venv/bin/python" "$ROOT/run_tracker.py" "$@"
