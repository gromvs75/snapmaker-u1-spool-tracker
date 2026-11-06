# Spoolman — Tracker 1.3.0

Tracker 1.3.0 with Spoolman integration. Supports **stock U1 firmware** and Spoolman **0.27.1**. Export a Tracker JSON backup before upgrading.
No changes to Snorca or printer firmware. Keeps the existing 1.2 beta / 1.2.1 inventory. Preview data is not imported automatically.
Data lives in `SnapmakerSpoolTracker-Beta12`; local UI port is 8766.
Printer monitoring starts disabled. Do not run two usage senders for the same U1.

In Settings → Spoolman, enter the server base URL (without `/api/v1` or credentials).
Choose read-only or explicitly confirm this Tracker is the sole usage sender for
this printer. Assign existing Spoolman spools to T0–T3. One physical spool cannot
feed two heads. Local spools remain available independently.

Slicing only forecasts. Known successful accounting results enqueue usage for
external spools instead of decrementing a separate local balance. Read-only mode
never submits usage, including old events after later enabling sending. Stale,
missing, archived or unknown stock and unresolved operations block a positive
forecast. External balances are edited in Spoolman, not locally.

A lost write response becomes **uncertain** and stops delivery. Review it explicitly:
Already applied (no send), Not applied: send (only after verification), or Close
without sending. A verification note is required. A changed balance alone is not
proof of our request. There is no automatic write retry or exactly-once guarantee
when the server response is lost.

Resolve pending operations before detaching, switching servers, or importing a
backup. Detach removes only the local link. For standalone use, create a local
spool with a verified balance. Restored backups disable sending and mark unfinished
operations uncertain; reconnect the same server and review them. Do not run copied
inventories on multiple computers as senders for one printer. The worker lock only
coordinates instances sharing the same data directory.

Limits: new settings text is RU/EN (English fallback for other languages), catalog
up to 10000 spools, 60-second freshness bound, no reverse-proxy authentication or
redirects. HTTPS retains certificate verification. macOS build is ad-hoc signed,
not notarized. **Windows GUI and real Snorca slicing on Windows remain unverified.**
Real U1 printing and long-running usage still need user validation. Scale-based
corrections v1.4 are deferred.

[Spoolman](https://github.com/Donkie/Spoolman), by Daniel Hultgren, is an independent
MIT-licensed project. This integration uses its API; its source is not bundled.

## U1 connection and JSON import

A fresh installation starts with the printer monitor disabled. `Disconnected · disabled`
means monitoring is off, not necessarily a network failure. Entering a host does not
start monitoring. Saving settings and testing the connection are separate actions;
a connection test does not enable automatic accounting.

A JSON backup restores the printer host/port and automatic-accounting setting,
in addition to inventory, assignments and history. If accounting was enabled in
the backup, importing it can reconnect the monitor. Import is not required to
configure a printer. Stop other Tracker instances accounting for this U1 before
import, and review monitoring settings afterward. Strict guard is reset to warn.

For the initial Spoolman read-only test, keep both usage delivery and printer
monitoring off. U1 connectivity is not required to browse the catalog. Spoolman
read-only mode does not disable accounting for local Tracker spools. Restoring a
backup disables the Spoolman integration separately; reconnect it explicitly.

The macOS menu-bar disappearance and window foreground issues were fixed in the previews and verified by the user. These fixes are retained in 1.3.0.

## Detailed setup and attribution

The full step-by-step Russian guide is `spoolman-ru.md` alongside this file.
Spoolman is a separate server; use version 0.27.1, not latest. On macOS, the upstream
recommended installation route is Docker: https://github.com/Donkie/Spoolman/wiki/Installation .
Use a persistent database volume and bind localhost for local-only tests. Create a
physical spool, not just a filament library entry. Start with read-only mode and
printer monitoring disabled. Assign the spool ID to one head, slice and check the
forecast. Enable usage only after confirming this Tracker is the sole sender for U1.
A matched registered print plan is required; slice observation alone is not registration.
See en.md for the existing slicer hook setup.

Export/import Tracker JSON through the native app window. Back up Spoolman's database
separately; Tracker JSON does not restore remote balances. Restore disables Spoolman
and makes unfinished operations uncertain. Reconnect the same server and audit them
before allowing retries. Never run two independent senders for the same printer.

The distribution includes the upstream MIT license and author attribution in licenses/.
Spoolman copyright (c) 2023 Daniel Hultgren; independent API integration, no endorsement.
Spoolman server/client code is not bundled. Windows GUI remains unverified.

For artificial-data testing, use a separate OS user account and test Spoolman server. Normal 1.3.0 startup uses the existing installed inventory; a separate archive is not an isolated database. The offline `--isolated-root` mode does not permit Spoolman connections.
