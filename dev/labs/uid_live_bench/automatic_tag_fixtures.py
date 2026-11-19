"""Synthetic cards using published Creality keys and real TigerTag vocabulary IDs.

Ciphertext and both AUTH keys were computed independently with OpenSSL ECB.
Neither this file nor the test claims a captured factory Creality RF dump.
"""
from .all_tag_fixtures import fixture as base_fixture,uid_for

PAYLOAD_KEY='484043466b526e7a404b4174424a7032'
CIPHER=bytes.fromhex('1406780898b717c476d4216a9635d1c0451bbce6fde582ab501b41101c3741c009c8591b580b01a28f29baf66299aee2')
KEYS={'4024C26A':'2577cf2e7f43','4124C26A':'d21b5c3ac7fa'}


def fixture(kind,side=0):
    b=base_fixture(kind,side)
    if kind=='creality':
        b[64:112]=CIPHER;b[122:128]=bytes.fromhex(KEYS[uid_for(kind,side)])
    if kind=='tigertag':
        b[24:26]=(38219).to_bytes(2,'big')  # Published PLA material ID.
        b[30:32]=(35123).to_bytes(2,'big')  # Published Bambu Lab brand ID.
        b[20:24]=bytes.fromhex('FFFFFFFF')  # Standard TigerTag, no product catalogue ID.
    return b
