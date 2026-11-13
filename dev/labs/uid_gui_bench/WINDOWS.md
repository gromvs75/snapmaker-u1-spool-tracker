# Windows GUI 2.0 — prepared, NOT verified

No Windows host, VM or remote desktop is available in this session; the owner
confirmed that no Windows test machine is available. macOS and browser testing
must not be reported as Windows GUI verification.

Use a separate disposable Windows environment with an existing Python environment,
pywebview and filelock, plus WebView2. No dependency installation or system change
is performed by this launcher. Do not run the installed Tracker or connect a
printer. Copy this development checkout to the isolated guest; no user database
is needed. This is not the old 1.2/Snorca Windows Sandbox kit.

From a PowerShell terminal in the guest:

```powershell
.\dev\labs\uid_gui_bench\Start-Windows.ps1 -Python 'C:\Path\To\PreparedEnv\python.exe'
```

The launcher selects Edge Chromium on Windows, serves only loopback on an
available port, and creates a fresh uid-gui-bench-* directory under Windows TEMP.
Its path is printed as DATA. All WebView storage is directed to that directory;
private mode is enabled. The launcher never searches installed Tracker data.
It writes run-info.json and, after closing the window, verification.json.
A returned native event loop or generated JSON alone does NOT prove UI success.

## Scenarios to actually perform on Windows

1. Verify Cyrillic text, radio cards, focus, keyboard/Escape, and layout at normal
   and enlarged display scaling. Open «Разрешить задание». Neither checkbox is
   selected; a single checkbox must not enable submission. Cancel changes nothing.
2. In DATA/print-state.txt set `printing` (ASCII/UTF-8 without BOM). With both
   acknowledgements checked, submission must fail. Set `cancelled` and retry.
3. Select 15 minutes and submit. Deadline appears; balances remain 499702 and
   299404 mg. Do not confirm the black spool yet.
4. Set DATA/clock-offset.txt to `901` (ASCII/UTF-8 without BOM). Within polling
   delay the block must return. Confirmation and transfer must be blocked.
5. Renew through the dialog, confirm the black spool, drag U1_1→U1_2 to a free
   head, and confirm the transfer. T1 is occupied. Identity and balance must stay
   unchanged. Set clock-offset.txt to `1802`; a completed window must not relock.
6. Close the window; retain run-info.json, verification.json, gui.sqlite, screenshot
   evidence and OS/WebView2 versions. Verify zero debits and one permanent resolution.
7. Start another fresh run and select «Снять до ручного назначения». The window
   has no deadline; confirmation completes it. Check keyboard operation too.

For repeated request/history and late debit protection, run the existing tests
on Windows in the same isolated checkout (requires pytest):

```powershell
python -m pytest tests/test_uid_unlock_window.py tests/test_uid_resolution.py tests/test_uid_motion_lifecycle.py tests/test_uid_gui.py -q
```

These accounting tests supplement native interactions; they do not replace them.
The clock-offset and print-state files are explicitly synthetic test fixtures.
No Windows execution, WebView2 behavior, DPI behavior or drag result has yet been
observed. Do not remove the project's Windows GUI warning until evidence exists.
