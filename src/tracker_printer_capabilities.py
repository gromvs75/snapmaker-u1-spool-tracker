"""Separate printer liveness from RFID evidence; never synthesize UID readiness."""


def printer_available(snapshot):
    # Older injected bench snapshots predate independent printer telemetry.
    # Production clients always provide printer_connected, with a freshness bound.
    if 'printer_connected' in snapshot:
        return snapshot['printer_connected'] is True
    return snapshot.get('state') == 'ready'


def manual_available(snapshot):
    return printer_available(snapshot) and snapshot.get('state') in (
        'ready', 'module_missing', 'module_unavailable')


def manual_edit_available(snapshot):
    return manual_available(snapshot) and snapshot.get('print_state', 'standby') in (
        'standby', 'complete', 'cancelled', 'error')


def can_replace_stale_uid(snapshot, location):
    return (snapshot.get('state') == 'module_missing'
            and manual_edit_available(snapshot) and not location['confirmed'])
