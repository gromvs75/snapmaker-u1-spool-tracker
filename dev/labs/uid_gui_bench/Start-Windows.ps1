param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'This launcher requires Windows.' }
# Use an already prepared isolated Windows test environment. No installation,
# production settings discovery, firewall changes, or printer connections.
& $Python -c 'import sys; import webview; import filelock; print(sys.version)'
if ($LASTEXITCODE -ne 0) { throw 'Prepared Python environment needs pywebview and filelock.' }
$runner = Join-Path $PSScriptRoot 'run.py'
& $Python $runner --window --resolution --port 0
if ($LASTEXITCODE -ne 0) { throw "GUI bench failed with exit code $LASTEXITCODE. Preserve the printed DATA directory." }
