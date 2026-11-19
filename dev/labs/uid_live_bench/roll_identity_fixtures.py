"""Synthetic OpenPrintTag instance IDs; not factory Prusa radio fixtures."""
from dev.labs.uid_live_bench.all_tag_fixtures import cbor, ndef

INSTANCE = bytes.fromhex('73646F54D4754C33A89C15C14AFA9D11')


def payload(instance=INSTANCE, **fields):
    main = {10: 'PLA Bench', 11: 'Bench filament', 52: 'PLA', 16: 1000,
            19: bytes.fromhex('778899FF'), 30: 1.75, 34: 190, 35: 230, 38: 60}
    if instance is not None:
        main[0] = instance
    main.update({int(k): v for k, v in fields.items()})
    return cbor({}) + cbor(main) + cbor({})


def pages(uid, instance=INSTANCE, **fields):
    return ndef(uid, 'application/vnd.openprinttag', payload(instance, **fields))
