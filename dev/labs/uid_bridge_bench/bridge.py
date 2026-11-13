"""Bench-only UID event adapter. No hardware, installation or inventory writes.

Consumes results from the patched reader, independently of filament decoding.
The live Klipper lifecycle and callback chaining are NOT implemented here.
"""
import copy
import uuid


def type2_uid(raw):
    # NTAG pages 0..2: 3 UID bytes, BCC0, 4 UID bytes, BCC1.
    if not isinstance(raw, (list, bytes, bytearray)) or len(raw) < 12:
        return None
    b = list(raw[:12])
    if any(type(v) is not int or not 0 <= v <= 255 for v in b):
        return None
    uid = b[:3] + b[4:8]
    if b[3] != (0x88 ^ uid[0] ^ uid[1] ^ uid[2]):
        return None
    if b[8] != (uid[3] ^ uid[4] ^ uid[5] ^ uid[6]):
        return None
    return uid


class UidBridge:
    def __init__(self):
        self.epoch = uuid.uuid4().hex
        self.sequence = 0
        self.channels = {str(i): {'state': 'unknown', 'uid': None} for i in range(4)}

    def enable_mifare_fallback(self, reader):
        # Bespok3d's driver only enters UID fallback if a claim handler exists.
        # Decline payload decoding; let the driver's own UID fallback handle it.
        reader.register_card_handler(lambda _: False, lambda _: None)

    def enable_type2_uid(self, reader, *, ok=0, ntag_type=0):
        # Read only four manufacturer pages: no NDEF/material decoder needed.
        # Register only on an otherwise unused extension slot in this bench.
        if 4 in reader._card_type_handlers:
            raise ValueError('NTAG handler already registered')
        def read_uid_pages(hw):
            result, raw = hw.read_nfc_type2_pages(0, 4)
            return ntag_type, raw if result == ok else None, result
        reader.register_card_type_handler(4, read_uid_pages)

    def observe(self, channel, operation, result, card_type, data, *, read_op, clear_op,
                ok, mifare_uid_type, ntag_type):
        if type(channel) is not int or not 0 <= channel < 4:
            return
        uid = None
        state = 'unreadable'
        if operation == clear_op:
            state = 'absent'
        elif operation == read_op and result == ok:
            if card_type == mifare_uid_type:
                if (isinstance(data, (list, bytes, bytearray)) and len(data) == 4
                        and all(type(x) is int and 0 <= x <= 255 for x in data)):
                    uid = list(data)
            elif card_type == ntag_type:
                uid = type2_uid(data)
            if uid and any(uid) and uid[0] != 0x08:
                state = 'present'
            else:
                uid = None
        self.sequence += 1
        self.channels[str(channel)] = {
            'state': state, 'uid': bytes(uid).hex().upper() if uid else None,
            'sequence': self.sequence,
        }

    def get_status(self):
        return copy.deepcopy({'epoch': self.epoch, 'sequence': self.sequence,
                              'channels': self.channels})
