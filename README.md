<img width="1672" height="941" alt="Snapmaker U1 Spool Tracker" src="docs/images/tracker-banner.png" />

*Original project banner; the pictured interface is from an earlier version. Current release: 1.3.2.*

# Snapmaker U1 Spool Tracker

**Spool tracking and usage forecasts for Snapmaker U1 — without firmware changes.**

Local filament inventory and automatic forecasts after slicing in Snapmaker Orca (Snorca).

Keep Tracker in the menu bar or tray and slice a model in Snorca. The icon and menu show estimated usage, balances and reserve-aware **✓ / ✕** indicators. On macOS the menu opens automatically after slicing; the main window opens only on request and there is no Dock icon. No manual G-code export is needed; slicing does not deduct filament or start printing.

**[Version 1.3.2 downloads](https://github.com/gromvs75/snapmaker-u1-spool-tracker/releases/tag/v1.3.2).** Packages target **macOS Apple Silicon (arm64)** and **Windows x64**.

**Windows GUI and real Snorca slicing on Windows remain unverified.** The earlier automatic-window behavior was not validated on Windows either. In 1.2.1 automatic menu opening is macOS-only; Windows updates the tray icon and menu without opening the dashboard. CI and executable self-tests do not replace desktop testing.

## First installation — macOS and Snorca

1. [Download 1.3.2](https://github.com/gromvs75/snapmaker-u1-spool-tracker/releases/tag/v1.3.2), unzip it and move `SnapmakerSpoolTracker-1.3.2.app` to `/Applications`. You may rename it to `SnapmakerSpoolTracker.app` for a version-independent path. Before replacing an older installation, export its JSON backup and quit it.
2. Open Tracker. From its menu-bar icon, choose **Configure Spools & Slots**, add your spools and assign T0–T3. Spoolman is optional; start with read-only mode if connecting it.
3. **For automatic accounting, configure Snorca:** open **Process / Print Settings → Others → Post-processing scripts**, paste the command below and save the process preset. If the field is hidden, enable advanced/expert settings. Replace an old Tracker command rather than adding a second one.

If you renamed the app to `SnapmakerSpoolTracker.app`:

```text
/Applications/SnapmakerSpoolTracker.app/Contents/MacOS/SnapmakerSpoolTracker;
```

If you kept the name from the 1.3.2 archive:

```text
/Applications/SnapmakerSpoolTracker-1.3.2.app/Contents/MacOS/SnapmakerSpoolTracker;
```

Use **one** command matching the installed app name. Keep the trailing semicolon; quote paths containing spaces. Do not paste this into printer Start G-code or Terminal. Check the saved preset for each print process you use.

4. To account for completed prints, enter the U1 address and port (normally `7125`) in Tracker, test the connection, enable automatic accounting and save. For Spoolman consumption, separately enable usage delivery and confirm the sole sender only after completing the [integration guide](docs/guides/spoolman-en.md).
5. First test with a small model: slice for the menu forecast, then export G-code through the configured preset **without starting a print** to check the hook. Post-processing registers the print plan; slicing/exporting/uploading never deducts filament. Accounting requires the matching file and a successfully observed print.

**Forecast versus accounting:** the menu forecast works without the post-processing command. Automatic accounting needs the registered plan from that command and printer monitoring. A green forecast alone does not confirm that accounting is configured.

**Windows:** extract the ZIP to a permanent folder and use the actual `.exe` path as the post-processing command; see the [Windows setup](docs/guides/en.md#installation-and-snorca-post-processing). **Windows GUI and real Snorca slicing remain unverified.**

[Russian setup guide](docs/guides/ru.md#установка-и-настройка-постобработки-snorca) · [English setup guide](docs/guides/en.md#installation-and-snorca-post-processing)

## Fixed in 1.3.2

An observed print that enters an error state before cancellation can now use its
verified pre-stop motion capture for partial accounting. Replayed history does
not deduct it twice. Missing capture or inconsistent counters still require
review; the full print estimate is never charged for a cancellation.
The completed-print forecast fix from 1.3.1 is retained.
[Changes, validation and limits](docs/releases/1.3.2.md).

## Spoolman integration — introduced in 1.3.0

**Connects through Tracker. No components need to be installed on the printer.**

1.3.0 introduced optional Spoolman 0.27.1 catalog/stock reading and confirmed-print usage delivery. Read-only mode never sends consumption. Sending requires explicit sole-sender confirmation; ambiguous writes require manual review. Spoolman is installed separately.
Start with read-only mode before enabling usage delivery. Real U1 printing with Spoolman and sustained operation still require user validation.
[Integration guide (RU)](docs/guides/spoolman-ru.md) ·
[English guide](docs/guides/spoolman-en.md) ·
[1.3.2 notes](docs/releases/1.3.2.md) ·
[Spoolman attribution and MIT license](docs/licenses/Spoolman-NOTICE.md).

## Start here

| What you need | Link |
|---|---|
| Installation, inventory and backups | [English guide](docs/guides/en.md) · [Russian guide](docs/guides/ru.md) |
| Changes and validation | [1.3.2 release notes](docs/releases/1.3.2.md) |
| Published downloads | [GitHub Releases](https://github.com/gromvs75/snapmaker-u1-spool-tracker/releases) |
| Help test Windows | [Offline test instructions](dev/windows_slice_check/README_RU.md) |
| All documentation and older versions | [Documentation index](docs/README.md) |
| Run, test or build the source | [Developer guide](docs/development.md) |

## Data and limitations

- 1.3.2 keeps the existing **1.2 beta inventory directory**. Test Menu 1/2 inventories and older stable data are not imported automatically. See the guides before importing a backup.
- Forecast mapping is **assumed: material 1→T0 … 4→T3**. This is visibly labelled and does not confirm the printer's actual mapping.
- Forecasts use the latest completed Snorca 2.4.1 slice and recorded balances. They are estimates, not a guarantee that a print will finish.
- For testing without printer access, use the documented `--isolated-root` mode with artificial data. Normal backup import can enable saved printer-monitor settings.

## Repository map

| Folder | Contents |
|---|---|
| [`src/`](src/) | Application modules |
| [`docs/`](docs/) | Current guides, release notes and archived manuals |
| [`tests/`](tests/) | Automated checks |
| [`dev/`](dev/) | Simulators, fixtures, isolated lab apps and historical validation records |
| [`packaging/`](packaging/) | Desktop build specification and app icon |
| [`requirements/`](requirements/) | Runtime, development and optional lab dependencies |
| [`scripts/`](scripts/) | Source-checkout helper scripts |

[MIT license](LICENSE). No cloud account is required.
