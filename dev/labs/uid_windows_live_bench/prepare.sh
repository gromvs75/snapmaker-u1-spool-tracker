#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-dev build-essential libffi-dev libsodium23 git ca-certificates
bench_source=/tmp/tracker-live-source
mkdir -p "$bench_source"
git clone -q https://github.com/Klipper3d/klipper.git "$bench_source/klipper"
git -C "$bench_source/klipper" checkout -q 56a9c605e121c6560f5c8b6c0e33bdda86de69a1
git clone -q https://github.com/Arksine/moonraker.git "$bench_source/moonraker"
git -C "$bench_source/moonraker" checkout -q b559b9a81161f958a43c2f527b6ad96f73310d5d
python3 -m venv "$bench_source/env"
"$bench_source/env/bin/pip" install -q "$bench_source/moonraker" greenlet cffi pyserial python-can msgspec websocket-client filelock
"$bench_source/env/bin/pip" freeze > "$bench_source/dependencies.txt"
