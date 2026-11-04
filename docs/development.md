# Development

Use a fresh source checkout and a separate virtual environment. Python 3.11 is used in CI. Application modules live in `src/`; isolated experiments live in `dev/labs/`. The top-level `run_tracker.py` is the source launcher.

## Setup and checks

```sh
python -m venv venv
# Activate venv using the command for your shell, then:
python -m pip install -r requirements/dev.txt -r requirements/sender.txt
python -m pip install -e . --no-deps
python -m pytest -q
python run_tracker.py --self-test
```

The editable install makes the `src/` modules available to development commands and subprocesses. It changes only the selected environment. Optional browser tests additionally need `requirements/sender-ui-test.txt` and a Playwright Chromium installation in a dedicated test directory. CI without those optional dependencies reports the browser module as skipped.

Do not launch the normal app to test printer isolation. Prepare a fresh test directory as described in the [user guide](guides/en.md#offline-developertest-mode), then run:

```text
python run_tracker.py --isolated-root PATH
```

## Desktop packages

Run from the repository root after installing the development requirements:

```sh
# macOS Apple Silicon
python -m PyInstaller --noconfirm --clean packaging/SnapmakerSpoolTracker.spec

# Windows x64 (run on Windows)
python -m PyInstaller --noconfirm --clean --paths . --paths src --windowed --onefile --name SnapmakerSpoolTracker-1.2-beta-Windows src/spool_tracker.py
```

CI runs tests, packages the application and executes `--self-test`. macOS additionally verifies the ad-hoc signature. This does not notarize the application and does not validate Windows GUI behavior. Builds and caches belong in ignored output directories, never alongside user data.

## Development tools

Run tools from the repository root after the editable install, for example `python -m dev.mock_u1`. Isolated window prototypes are invoked as `python -m dev.labs.forecast_lab_app` or `python -m dev.labs.sender_test_app`. These are experimental tools, not the ordinary forecast workflow. Read their instructions before running them.

See [dev/](../dev/README.md) for fixtures and lab scope. Historical source commands in archived reports refer to the layout used at the time; use this guide for current paths.
