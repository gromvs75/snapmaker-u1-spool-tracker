# Spoolman compare editor — test implementation

Separate checkout: `output/spoolman-compare-editor`, branch `ui/spoolman-compare-editor`, based on rc3 (`091b300`). Not a published release or an installed application update.

## Visual specification

Chosen variant: **Dual-column compare editor: Tracker name vs Spoolman canonical name with one-click sync**.

Source: https://design.lazyweb.com/report/lazyweb/06129481-9eda-4d99-afc9-4f0097550df0/?source=create

The actual Mockup 1 image was opened and inspected at its native 1400×1050 size. It is a light wireframe with grey placeholder bars, not a dark Tracker screenshot and not a text-complete specification. Implementation follows its geometry, hierarchy and orange emphasis. Placeholder bars are replaced with live spool data and Russian/English labels; other application languages currently use English in this workspace.

Compared against the image and iterated twice: four top slot cards, middle four-row inventory, lower split catalog/detail area, left navigation rail, full-height right comparison panel, divider, full-width orange sync button and selected spool outline. Browser measurements at 1400×1050:

| Element | x / y | width / height |
| --- | --- | --- |
| Slots card | 105 / 28 | 806.5 / 214 |
| Inventory card | 105 / 256 | 806.5 / 301 |
| Catalog card | 105 / 572 | 806.5 / 461 |
| Right editor | 921.5 / 21 | 465.5 / 1013 |
| Sync button | 960.5 / 430.3 | 399 / 46 |

Reference and screenshots remain untracked under `output/`: `compare-reference.jpg`, `compare-desktop-final.png`, `compare-mobile-final.png`. At 390 px the editor moves above the inventory with no horizontal overflow; this responsive state is an adaptation because the supplied image only specifies desktop.

## Product integration

Open via **Compare names / Сравнить названия** in the spool inventory or Spoolman settings. The comparison workspace is a modal dialog with normal navigation back to the existing dashboard and Escape support. Select a spool from the inventory, source list, head cards or right-hand list. Filters cover all, differing, matching and local spools.

`spoolman_compare_view.py` installs the interface into the real dashboard HTML. `GET /api/spoolman/compare` returns current and canonical names. `POST /api/spoolman/refresh-labels` refreshes only cached catalog data. `POST /api/spoolman/sync-label` changes only the selected local label.

The server composes the name; it does not accept an arbitrary replacement string from the browser. A revision binds the reviewed source, connection epoch, local name and proposed name. A stale revision or unavailable, archived, outdated, or disconnected source blocks synchronization. These routes use the existing dashboard host/origin/content-type guards.

Sync does not change material, color, balance, assignment, print history or consumption outbox. It does not PUT to Spoolman or contact the printer. Material and color columns provide context; they are not bulk-editable. Existing rc3 automatic label refresh remains in place, so many rows will already match; if it updates a name while the comparison is open, the revision check prevents applying an outdated review.

## Isolated preview

```sh
PYTHONPATH=src python -m dev.labs.spoolman_compare.demo
```

The command creates a new `output/compare-preview-*` directory with synthetic inventory, starts the normal dashboard handler on a random loopback port and prints a URL ending in `#spoolman-compare`. It does not start the application tray, monitor, motion recorder or Spoolman worker. Its Spoolman adapter is an in-memory catalog. Printer, connection configuration and other mutation endpoints are explicitly blocked. It never reads the installed inventory.

The fixture intentionally starts with old labels to demonstrate repair. Refresh in the comparison panel fetches metadata without silently applying it; the Sync action then updates the selected name.

## Verification

- Full automated suite: **501 passed, 5 skipped** (Mac test environment).
- Fifteen new comparison cases cover read-only comparison, name-only synchronization with a pending consumption operation, stale names/catalogs/epochs, missing or archived spools, disabled/offline connections, stale timestamps, metadata-only refresh, older cached catalogs and refusal to target a local spool.
- Browser check used the real POST endpoint and compared the entire before/after inventory: only the selected name changed.
- Browser checks covered matching/difference/local filters, local-spool protection, Escape, reopening, simulated error responses, unavailable source and empty state.
- Final desktop and 390 px screenshots inspected after CSS adjustments. Final page console: zero errors and warnings. Deliberate failed-request testing was performed separately.

Native Windows/webview behavior for this new workspace remains UNVERIFIED. No new application package, release, printer operation or installed database migration was performed.
