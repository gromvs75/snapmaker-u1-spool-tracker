# Snapmaker U1 Spool Tracker

Local filament inventory and automatic forecasts after slicing in Snapmaker Orca (Snorca).

Keep Tracker in the menu bar or tray and slice a model in Snorca. The icon and menu show estimated usage, balances and reserve-aware **✓ / ✕** indicators. On macOS the menu opens automatically after slicing; the main window opens only on request and there is no Dock icon. No manual G-code export is needed; slicing does not deduct filament or start printing.

**1.2.1 is being prepared; it is not published.** The previous [1.2 beta pre-release](https://github.com/gromvs75/snapmaker-u1-spool-tracker/releases/tag/v1.2.0-beta) is available. Packages target **macOS Apple Silicon (arm64)** and **Windows x64**.

**Windows GUI and real Snorca slicing on Windows remain unverified.** The earlier automatic-window behavior was not validated on Windows either. In 1.2.1 automatic menu opening is macOS-only; Windows updates the tray icon and menu without opening the dashboard. CI and executable self-tests do not replace desktop testing.

## Start here

| What you need | Link |
|---|---|
| Installation, inventory and backups | [English guide](docs/guides/en.md) · [Русская инструкция](docs/guides/ru.md) |
| Changes and validation | [1.2.1 release notes](docs/releases/1.2.1.md) |
| Published downloads | [GitHub Releases](https://github.com/gromvs75/snapmaker-u1-spool-tracker/releases) |
| Help test Windows | [Offline test instructions](dev/windows_slice_check/README_RU.md) |
| All documentation and older versions | [Documentation index](docs/README.md) |
| Run, test or build the source | [Developer guide](docs/development.md) |

## Data and limitations

- 1.2.1 keeps the existing **1.2 beta inventory directory**. Test Menu 1/2 inventories and older stable data are not imported automatically. See the guides before importing a backup.
- Forecast mapping is **assumed: material 1→T0 … 4→T3**. This is visibly labelled and does not confirm the printer's actual mapping.
- Forecasts use the latest completed Snorca 2.4.1 slice and recorded balances. They are estimates, not a guarantee that a print will finish.
- For testing without printer access, use the documented `--isolated-root` mode with artificial data. Normal backup import can enable saved printer-monitor settings.

## Repository map

| Folder | Contents |
|---|---|
| [`src/`](src/) | Application modules |
| [`docs/`](docs/) | Current guides, release notes, archived manuals and unposted announcement copy |
| [`tests/`](tests/) | Automated checks |
| [`dev/`](dev/) | Simulators, fixtures, isolated lab apps and historical validation records |
| [`packaging/`](packaging/) | Desktop build specification and app icon |
| [`requirements/`](requirements/) | Runtime, development and optional lab dependencies |
| [`scripts/`](scripts/) | Source-checkout helper scripts |

[MIT license](LICENSE). No cloud account is required.
