# Manual mode and RFID in the 2.0 candidate

Manual assignments do not require the `tracker_uid` printer module or Klipper
configuration changes. Printer connectivity, print state and RFID capability are
checked separately. “RFID / UID · no module” does not mean the printer is offline.

Save the Moonraker address under **Settings → Printer** and explicitly connect.
Create/select a local or Spoolman-linked spool, open **Spools → Heads T0–T3**, select
the actual spools and confirm their placement while the printer is idle.
Confirmation changes no balance. Continuous observation allows usage to be charged
to the confirmed spools. Update the assignment when physically replacing a spool.

A spool with a stored UID may also be assigned manually when there is no competing
live RFID claim. This is still manual identity. If the same spool appears at two
locations, both become unusable until the conflict is resolved.

A connection gap invalidates manual confirmation. Check placement again after
reconnection, when the printer is idle. Resolve an interrupted job through history
first: inspect its saved plan, edit additional quantities and explicitly confirm.
Previously accounted quantities are protected against duplicate debits.
Reconfirmation cannot retroactively prove continuity of an interrupted job.

Balance correction, placement confirmation and job accounting are separate actions.
If you already corrected a balance for that usage, close the job without another
debit. Uncertain Spoolman deliveries still require reconciliation and explicit
approval; a reconnect or backup restore does not automatically resend them.

Saved inventory and history remain available offline. Authorizing a current physical
assignment for automatic accounting requires fresh idle printer telemetry. Invalid
UID data never silently falls back to trusted manual identity.

## RFID requirements and current limits

The path is: U1 reader → compatible `tracker_uid` Klipper extra → Moonraker object →
Tracker → persistent SQLite spool identity. UID is an identifier, not a measured
remaining mass. Registration attaches an observed tag to an existing spool or
creates a spool with explicitly provided material and balance.

Integration uses a Python extra plus a separate `tracker_uid.cfg` included by
`[include tracker_uid.cfg]`. A configuration line alone is insufficient. Replacing
the whole firmware is not the current approach. Compatibility must be checked
against the actual printer reader driver version/hash.

**Real U1 installation and physical RF reading have not been validated in this
stage.** The existing installer is deliberately restricted to marked filesystem
simulators, with backups and rollback. It is not a user-facing printer installer.
Do not apply bench commands to a real printer.

[Installation/rollback kit instructions and limits](rfid-module-install-en.md).

The RFID button and registration panel distinguish ready, missing module, reader
not ready, incompatible/invalid data, stopped connections and offline. Ready channels
show per-head read/no-tag/unreadable/stale/conflict states. Zero pending tags does
not prove the RFID channel works. Registration requires an observed tag and explicit
attachment confirmation; duplicate packets do not create duplicate spools.

Physical validation requires separate authorization, an idle printer, driver
compatibility inspection and prepared rollback. Autorefill and pre-send slicer
material-to-head mapping remain separate investigations with unchanged safeguards.
