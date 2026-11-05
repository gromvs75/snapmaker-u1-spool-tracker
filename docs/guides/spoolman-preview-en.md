# Spoolman Preview 1

Separate test app for **stock U1 firmware**, supporting Spoolman **0.27.1**.
No changes to Snorca or printer firmware. No installed inventory is imported.
Data lives in `SnapmakerSpoolTracker-SpoolmanPreview1`; local UI port is 8771.
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
