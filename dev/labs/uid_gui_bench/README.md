# Manual assignment and transfer GUI bench

```sh
python dev/labs/uid_gui_bench/run.py
# Optional native desktop shell (requires compatible pywebview and platform renderer):
python dev/labs/uid_gui_bench/run.py --window
```

The runner always creates a fresh `uid-gui-bench-*` SQLite database under the operating system temporary directory
and two simulated printers; there is no printer network client or installed
Tracker import. UI serves only on 127.0.0.1:18749. Ctrl-C closes the test database.
The HTML in src/tracker_uid_gui.html is shared by browser and pywebview modes.
`browser_check.js` is a Playwright async(page) function; execute against a fresh
runner. It verifies confirmation/cancel, transfer, retained mass, persistence,
occupied targets, token requirement, narrow viewport, duplicate requests, stale
versions and explicit refresh. Backend tests are `tests/test_uid_gui.py`.
Native Windows GUI is not verified. This phase tested the browser-rendered GUI,
not installation into the user's existing desktop application.

Windows preparation and its unverified status: `WINDOWS.md` in this folder.
Every run writes `run-info.json` and, on shutdown, `verification.json` to its
fresh temporary directory. These are evidence, not an automatic GUI pass.
