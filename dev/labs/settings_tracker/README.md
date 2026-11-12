# Settings integration lab (rc5 source base)

This runs the actual Tracker HTML, WebHandler, Store and Spoolman Bridge with a disposable inventory and an in-process catalog fixture. It is not a packaged release and is separate from the installed application and 2.0.0.

From this checkout, with the project's development dependencies available:

```sh
PYTHONPATH=src:. python -m dev.labs.settings_tracker.server
```

Open the printed URL. Each start creates `output/settings-tracker-*/inventory`. The process remains alive until stopped. Reloading the page retains changes in that test database; restarting creates a fresh one. Generated data must not be committed.

## What is real

- Overview, Spools, History and Settings remain the Tracker navigation.
- Saving printer configuration, accounting/guard options and reserve uses existing API validation and storage.
- Spoolman configuration, catalog refresh, assignment, detach and label comparison use the real Bridge, against fixture catalog entries.
- Settings has four sections. Form actions stay inside their cards. Spoolman catalog entries have colored SVG spools, search, selection and a uniform right-hand action column.
- RU/EN labels; existing language selection remains available (new layout labels fall back to English for other languages).

## Boundaries

No PrinterMonitor or Spoolman sender worker starts. HTTP routes that can access the printer, sender or accounting reconciliation are rejected. The catalog factory accepts only `http://127.0.0.1:1` and returns fixture data; it never opens a connection. `socket.create_connection` is disabled in this standalone process as an additional guard. Editing the printer address or enabling accounting saves test configuration only. No installed inventory is opened. Desktop-only backup remains unavailable in the browser; no fake successful export is shown.

The approved settings prototype remains in `dev/labs/settings_preview/`. This integrated variant builds on its agreed layout, restores the main navigation and places save buttons inside their forms, following user feedback. It does not port the separate experimental batch-name-sync branch or merge anything into 2.0.0.

## Browser verification

- Saved reserve 12 g, accounting enabled and `lab-printer.invalid`; values persisted across page reload.
- Assigned the fixture Gold spool to T3, then detached it through the UI; catalog balance stayed 920 g.
- Switched Spoolman to read-and-send with sole-sender confirmation; saved mode persisted. No delivery worker was started.
- Search, empty results, main navigation and settings sections checked.
- Printer API route returned 403 as intended.
- Right-side action buttons have equal x-coordinate and width (222 px at 1440 px viewport).
- No horizontal overflow at 700 px; no JavaScript console errors in the final run.

Native Windows/Mac GUI and real printer communication have not been tested in this change. No application build or CI build was requested or produced.

Full regression run: **501 passed, 5 skipped** (`PYTHONPATH=src:. /private/tmp/tracker-cancel-test-env/bin/python -m pytest -q`). The project's older `venv` lacked `websockets`; it was not modified. The complete run used an existing separate test environment.
