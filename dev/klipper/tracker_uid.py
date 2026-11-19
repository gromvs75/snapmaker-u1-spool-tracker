"""Experimental Klipper UID observer; validated on software bench only.

Install before Klipper startup. Optional multiformat reads; no tag writes.
"""
import copy
import inspect
import logging
import sys
import time
import hashlib
import threading
import uuid
import hmac
import math
import struct
from pathlib import Path

P = '_FM175XXReader__'

# Public Bambu RFID memory map and HKDF parameters (not a user credential).
# Research references are recorded in docs/development/rfid-bambu-2026-11-19.md.
BAMBU_SALT = bytes.fromhex('9a759cf2c4f7caff222cb9769b41bc96')


def bambu_keys(uid):
    if len(uid) != 4:
        raise ValueError('Bambu M1 requires a four-byte UID')
    seed = hmac.new(BAMBU_SALT, bytes(uid), hashlib.sha256).digest()
    material, previous = b'', b''
    for n in range(1, 4):
        previous = hmac.new(seed, previous + b'RFID-A\0' + bytes([n]), hashlib.sha256).digest()
        material += previous
    return [material[n:n+6] for n in range(0, 96, 6)]


def decode_bambu_blocks(uid, blocks):
    """Decode authenticated data blocks, never a remaining-weight claim.

    Block 9 identifies the physical roll shared by its two chip UIDs. Partial
    reads cannot create a second roll under a fallback chip identity.
    """
    required = (0, 1, 2, 4, 5, 6, 9)
    if any(n not in blocks or len(blocks[n]) != 16 for n in required):
        raise ValueError('Incomplete Bambu data')
    b = {n: bytes(v) for n, v in blocks.items()}
    if b[0][:4] != bytes(uid):
        raise ValueError('Tag changed during read')
    def text(value):
        value = value.split(b'\0', 1)[0].decode('ascii').strip()
        if not value or any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError('Invalid material text')
        return value
    material_id, variant = text(b[1][8:]), text(b[1][:8])
    if not material_id.startswith('GF'):
        raise ValueError('Unrecognized Bambu layout')
    diameter = struct.unpack_from('<f', b[5], 8)[0]
    weight = int.from_bytes(b[5][4:6], 'little')
    if not math.isfinite(diameter) or not .5 <= diameter <= 4 or not 1 <= weight <= 10000:
        raise ValueError('Invalid nominal dimensions')
    if not any(b[9]) or b[9] == b'\xff' * 16:
        raise ValueError('Missing Bambu roll identity')
    colors = [b[5][:3].hex().upper()]
    if 16 in b and len(b[16]) == 16 and b[16][:4] == b'\x02\0\x02\0':
        colors.append(b[16][4:8][::-1][:3].hex().upper())
    low, high = struct.unpack_from('<H', b[6], 10)[0], struct.unpack_from('<H', b[6], 8)[0]
    if not 100 <= low <= high <= 400:
        raise ValueError('Invalid temperature range')
    return dict(schema=1, format='bambu', uid=bytes(uid).hex().upper(),
                identity='bambu:' + b[9].hex().upper(), manufacturer='Bambu Lab',
                material=text(b[2]), name=text(b[4]), material_id=material_id,
                variant_id=variant, color=colors[0], colors=colors, alpha=b[5][3],
                diameter_mm=round(diameter, 4), nominal_weight_g=weight,
                nozzle_min_c=low, nozzle_max_c=high,
                bed_c=int.from_bytes(b[6][6:8], 'little'))


def read_bambu(reader, fm, uid, activate):
    """Bounded read-only transaction in the stock reader's own thread.

    Only AUTH A and block READ go through the unchanged approved stock driver.
    The caller has already let the stock read fail; its result remains unchanged.
    """
    if len(uid) != 4 or getattr(reader, P+'picc_a').SAK[0] != 8:
        return None
    keys = bambu_keys(uid)
    getattr(reader, P+'reader_a_init')()
    getattr(reader, P+'set_carrier_wave')(fm.FM175XX_CW_ENABLE)
    if activate() != fm.FM175XX_OK or selected_uid(getattr(reader, P+'picc_a')) != list(uid):
        raise ValueError('Tag changed or unavailable')
    blocks = {}
    for sector, indexes in ((0, (0, 1, 2)), (1, (4, 5, 6)), (2, (9,)), (4, (16,))):
        if getattr(reader, P+'stop_event').is_set():
            raise ValueError('Reader stopping')
        if getattr(reader, P+'reader_a_mifare_auth')(
                fm.FM175XX_M1_CARD_AUTH_MODE_A, sector, list(keys[sector]), list(uid)) != fm.FM175XX_OK:
            if sector == 4:
                break  # Optional second colour only; never invent its value.
            raise ValueError('Bambu authentication unavailable')
        for index in indexes:
            result = getattr(reader, P+'reader_a_m1_block_read')(index)
            if result.err_code != fm.FM175XX_OK or len(result.out_param) != 16:
                if sector == 4:
                    break
                raise ValueError('Bambu block unreadable')
            blocks[index] = bytes(result.out_param)
    return decode_bambu_blocks(uid, blocks)


def decode_qidi(uid, block):
    """Published three-byte layout; absent and unmapped properties stay unknown."""
    block = bytes(block)
    if len(uid) != 4 or len(block) != 16 or not all(block[:3]) or any(block[3:]):
        raise ValueError('Not a QIDI layout')
    material, name = {2: ('PLA', 'PLA Matte'), 0x29: ('PETG', 'PETG')}.get(
        block[0], (None, 'Unknown QIDI material %02X' % block[0]))
    color = {1: 'FFFFFF', 0x0B: '1714B0', 0x12: 'FF362D', 0x14: '898F9B'}.get(block[1])
    ident = bytes(uid).hex().upper()
    return dict(schema=1, format='qidi', uid=ident, identity='qidi:chip:'+ident,
                manufacturer='QIDI' if block[2] == 1 else 'QIDI-compatible',
                material=material, name=name, material_id='qidi:%02X' % block[0],
                variant_id='%02X:%02X' % (block[1], block[2]),
                color=color, colors=[color] if color else [], alpha=255,
                diameter_mm=None, nominal_weight_g=None, nozzle_min_c=None,
                nozzle_max_c=None, bed_c=None, material_code=block[0],
                color_code=block[1], manufacturer_code=block[2])


def decode_anycubic(uid, data):
    """Known ACE page layout, anchored to page 4; no guessed roll serial."""
    data = bytes(data)
    if (len(uid) != 7 or len(data) < 128 or data[16:18] != b'\x7b\0'
            or data[18] not in (0x64, 0x65) or data[19] != 0
            or data[:3]+data[4:8] != bytes(uid)):
        raise ValueError('Invalid Anycubic pages or changed UID')
    def text(offset, size, optional=False):
        field = data[offset:offset+size]
        if b'\0' not in field:
            raise ValueError('Unterminated Anycubic field')
        value = field.split(b'\0', 1)[0].decode('ascii').strip()
        if (not value and not optional) or any(not 32 <= ord(c) <= 126 for c in value):
            raise ValueError('Invalid Anycubic text')
        return value
    # Public samples do not settle 12 versus 16 SKU bytes. Do not consume an
    # adjacent unknown field as SKU on a tag that reaches that boundary.
    sku = text(20, 12)
    brand = text(40, 16, True)
    material = text(60, 20).upper()
    u16 = lambda offset: int.from_bytes(data[offset:offset+2], 'little')
    diameter, weight = u16(120)/100., u16(124)
    low, high = u16(96), u16(98)
    if not .5 <= diameter <= 4 or not 1 <= weight <= 10000 or not 100 <= low <= high <= 400:
        raise ValueError('Invalid Anycubic dimensions or temperature')
    if not 0 <= u16(116) <= u16(118) <= 200:
        raise ValueError('Invalid Anycubic bed range')
    color = data[81:84][::-1].hex().upper()
    ident = bytes(uid).hex().upper()
    return dict(schema=1, format='anycubic', uid=ident, identity='anycubic:chip:'+ident,
                manufacturer='Anycubic', material=material, name=material+' '+sku,
                material_id='anycubic:'+sku, variant_id=sku, sku=sku, brand_code=brand,
                color=color, colors=[color], alpha=data[80], diameter_mm=diameter,
                nominal_weight_g=weight, nozzle_min_c=low, nozzle_max_c=high,
                bed_c=u16(118), bed_min_c=u16(116), length_m=u16(122),
                print_speed_min=u16(92), print_speed_max=u16(94), layout_version=data[18])


def read_qidi(reader, fm, uid, activate):
    if len(uid) != 4 or getattr(reader, P+'picc_a').SAK[0] != 8:
        return None
    getattr(reader, P+'reader_a_init')()
    getattr(reader, P+'set_carrier_wave')(fm.FM175XX_CW_ENABLE)
    if activate() != fm.FM175XX_OK or selected_uid(getattr(reader, P+'picc_a')) != list(uid):
        raise ValueError('QIDI tag changed')
    if getattr(reader, P+'stop_event').is_set():
        raise ValueError('Reader stopping')
    if getattr(reader, P+'reader_a_mifare_auth')(fm.FM175XX_M1_CARD_AUTH_MODE_A, 1, [255]*6, list(uid)) != fm.FM175XX_OK:
        raise ValueError('QIDI authentication failed')
    result = getattr(reader, P+'reader_a_m1_block_read')(4)
    if result.err_code != fm.FM175XX_OK:
        raise ValueError('QIDI block unavailable')
    return decode_qidi(uid, result.out_param)


def read_anycubic(reader, fm, uid, activate):
    picc = getattr(reader, P+'picc_a')
    if len(uid) != 7 or picc.SAK[picc.CASCADE_LEVEL] != 0:
        return None
    # Stock's block-read primitive emits the same 0x30 READ command as Type 2:
    # the address denotes a four-byte page and the reply is four pages (16B).
    data = bytearray()
    for page in range(0, 32, 4):
        if getattr(reader, P+'stop_event').is_set():
            raise ValueError('Reader stopping')
        result = getattr(reader, P+'reader_a_m1_block_read')(page)
        if result.err_code != fm.FM175XX_OK or len(result.out_param) != 16:
            raise ValueError('Anycubic page unavailable')
        data.extend(result.out_param)
        if page == 4 and data[16:20] not in (b'\x7b\0\x64\0', b'\x7b\0\x65\0'):
            return None
    if activate() != fm.FM175XX_OK or selected_uid(getattr(reader, P+'picc_a')) != list(uid):
        raise ValueError('Anycubic tag changed during read')
    return decode_anycubic(uid, data)


# Additional formats: independent implementation of the documented memory maps.
# Reference revision and limits: docs/development/rfid-all-formats-2026-11-19.md.

def _gf(a, b):
    result = 0
    for _ in range(8):
        if b & 1: result ^= a
        a = ((a << 1) ^ (0x11b if a & 128 else 0)) & 255
        b >>= 1
    return result


def _aes_tables():
    forward = []
    for n in range(256):
        x, power, inverse = n, 254, 1
        while power:
            if power & 1: inverse = _gf(inverse, x)
            x = _gf(x, x); power >>= 1
        if n == 0: inverse = 0
        value = inverse ^ 0x63
        for shift in (1, 2, 3, 4):
            value ^= ((inverse << shift) | (inverse >> (8-shift))) & 255
        forward.append(value)
    reverse = [0]*256
    for i, v in enumerate(forward): reverse[v] = i
    return forward, reverse


_AES_TABLES = None


def aes128(key, data, decrypt=False):
    """AES-128 ECB for the fixed Creality payload only (FIPS 197).

    No native dependencies, no padding, no tag-write operation. Not intended as
    a general cryptographic API or for protecting application secrets.
    """
    global _AES_TABLES
    if len(key) != 16 or not data or len(data) % 16:
        raise ValueError('Invalid AES block/key length')
    if _AES_TABLES is None: _AES_TABLES = _aes_tables()
    sbox, inverse = _AES_TABLES
    expanded = list(key); rc = 1
    while len(expanded) < 176:
        t = expanded[-4:]
        if len(expanded) % 16 == 0:
            t = [sbox[v] for v in t[1:]+t[:1]]; t[0] ^= rc; rc = _gf(rc, 2)
        for v in t: expanded.append(expanded[-16] ^ v)
    def add(state, round_):
        return [v ^ k for v, k in zip(state, expanded[16*round_:16*(round_+1)])]
    def shift(state, reverse=False):
        return [state[4*((c + (-r if reverse else r)) % 4)+r] for c in range(4) for r in range(4)]
    def mix(state, reverse=False):
        first = (14, 11, 13, 9) if reverse else (2, 3, 1, 1)
        return [sum_xor([_gf(state[c*4+k], first[(k-r) % 4]) for k in range(4)])
                for c in range(4) for r in range(4)]
    result = bytearray()
    for offset in range(0, len(data), 16):
        state = add(list(data[offset:offset+16]), 10 if decrypt else 0)
        for round_ in (range(9, -1, -1) if decrypt else range(1, 11)):
            if decrypt:
                state = add([inverse[v] for v in shift(state, True)], round_)
                if round_: state = mix(state, True)
            else:
                state = shift([sbox[v] for v in state])
                if round_ != 10: state = mix(state)
                state = add(state, round_)
        result.extend(state)
    return bytes(result)


def sum_xor(values):
    result = 0
    for v in values: result ^= v
    return result


def _optional_number(value, low, high):
    if value is None: return None
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Invalid tag numeric field')
    return value


def _tag_text(value, optional=False):
    if value in (None, '') and optional: return None
    if not isinstance(value, str) or not 1 <= len(value) <= 64 or any(ord(c)<32 or ord(c)>126 for c in value):
        raise ValueError('Invalid tag text')
    return value


def chip_metadata(kind, uid, manufacturer, material, colors, *, code=None, name=None,
                  variant='default', diameter=None, weight=None, low=None, high=None, bed=None, alpha=255):
    ident = bytes(uid).hex().upper()
    if len(uid) != (4 if kind == 'creality' else 7): raise ValueError('Invalid chip UID')
    material = _tag_text(material, True)
    if len(colors) > 5 or any(not isinstance(c,str) or len(c)!=6 or any(x not in '0123456789ABCDEF' for x in c) for c in colors):
        raise ValueError('Invalid tag colors')
    low = _optional_number(low, 100, 400); high = _optional_number(high, 100, 400)
    if low is not None and high is not None and low > high: raise ValueError('Inverted tag temperatures')
    return dict(schema=1, format=kind, uid=ident, identity=kind+':chip:'+ident,
                manufacturer=_tag_text(manufacturer), material=material,
                name=_tag_text(name or material or 'Unknown material'),
                material_id=_tag_text(kind+':'+(code or material or 'unknown')),
                variant_id=_tag_text(variant), colors=colors, color=colors[0] if colors else None,
                alpha=_optional_number(alpha,0,255), diameter_mm=_optional_number(diameter,.5,4),
                nominal_weight_g=_optional_number(weight,1,10000), nozzle_min_c=low, nozzle_max_c=high,
                bed_c=_optional_number(bed,0,200))


# Confirmed material ID facts from published Creality profile/decoder references.
# Unknown IDs remain unknown; physical properties must be configured, not guessed.
CREALITY_MATERIALS = {
    '00001':'PLA', '00002':'PLA', '00003':'PETG', '00004':'ABS', '00005':'TPU',
    '00006':'PLA-CF', '00007':'ASA', '00008':'PA', '00009':'PA-CF', '00010':'BVOH',
    '00011':'PVA', '00012':'HIPS', '00013':'PET-CF', '00014':'PETG-CF',
    '01001':'PLA', '01002':'PLA', '01003':'PLA', '01004':'PLA', '02001':'PLA-CF',
    '03001':'ABS', '04001':'PLA', '05001':'PLA', '06001':'PETG', '06002':'PETG',
    '06003':'PETG-CF', '06004':'PETG-GF', '07001':'ABS', '07002':'PC',
    '08001':'PLA', '09001':'PLA', '10001':'TPU', '11001':'PA', '19001':'ASA',
    'E1001':'PLA', 'E2001':'PETG', 'E3001':'ABS', 'E4001':'ASA', 'E5001':'TPU'}


# Public, shared Creality protocol keys, NOT a user's credential.
# DnG-Crafts/K2-RFID 7101bac4499a76e64b39460b63a8c3f446e5c127, AES.cpp.
# SHA256 independently matches the Bespok3d published expected key hashes.
CREALITY_MASTER = bytes.fromhex('713362755e74316e71665a2870662431')
CREALITY_PAYLOAD = bytes.fromhex('484043466b526e7a404b4174424a7032')


def configured_creality_keys(config):
    values=[config.get(name,None) for name in ('creality_master_key','creality_payload_key')]
    if values==[None,None]:return CREALITY_MASTER,CREALITY_PAYLOAD
    # An explicit override must provide BOTH keys. Never silently replace a bad
    # or deliberately empty override with the defaults.
    try:
        keys=tuple(bytes.fromhex(v) for v in values)
        if all(len(k)==16 for k in keys):return keys
    except (ValueError,TypeError):pass
    return None,None


def decode_creality(uid, plain):
    if len(plain) != 48 or b'%' not in plain: raise ValueError('Invalid Creality frame')
    core, tail = plain.split(b'%', 1)
    if any(tail) or not 28 <= len(core) <= 47: raise ValueError('Invalid Creality padding')
    text = core.decode('ascii').upper()
    # IDs may contain letters beyond F (e.g. P1001); the rest is hexadecimal.
    if (any(c not in '0123456789ABCDEF' for c in text[:12]+text[17:])
            or any(c not in '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ' for c in text[12:17])):
        raise ValueError('Invalid Creality core')
    code = text[12:17]
    return chip_metadata('creality',uid,'Creality',CREALITY_MATERIALS.get(code),[text[18:24]],code=code,
                         name='Creality '+code, weight={'0082':250,'0165':500,'0198':600,'0247':750,'0330':1000}.get(text[24:28]))


def read_creality(reader, fm, uid, activate, master, payload_key):
    if len(uid)!=4 or getattr(reader,P+'picc_a').SAK[0]!=8 or master is None or payload_key is None: return None
    key = list(aes128(master,bytes(uid)*4)[:6])
    getattr(reader,P+'reader_a_init')();getattr(reader,P+'set_carrier_wave')(fm.FM175XX_CW_ENABLE)
    if activate()!=fm.FM175XX_OK or selected_uid(getattr(reader,P+'picc_a'))!=list(uid):
        raise ValueError('Creality tag changed')
    if getattr(reader,P+'reader_a_mifare_auth')(fm.FM175XX_M1_CARD_AUTH_MODE_B,1,key,list(uid))!=fm.FM175XX_OK:
        raise ValueError('Creality authentication failed')
    data = bytearray()
    for block in (4,5,6):
        if getattr(reader,P+'stop_event').is_set(): raise ValueError('Reader stopping')
        r=getattr(reader,P+'reader_a_m1_block_read')(block)
        if r.err_code!=fm.FM175XX_OK or len(r.out_param)!=16: raise ValueError('Incomplete Creality read')
        data.extend(r.out_param)
    if activate()!=fm.FM175XX_OK or selected_uid(getattr(reader,P+'picc_a'))!=list(uid):
        raise ValueError('Creality tag changed during read')
    return decode_creality(uid,aes128(payload_key,data,True))


def decode_elegoo(uid, data):
    matches=[n for n in range(16,len(data)-31,4) if data[n:n+5]==bytes.fromhex('36EEEEEEEE')]
    if len(matches)!=1: raise ValueError('Missing/ambiguous Elegoo block')
    n=matches[0]; b=data[n:n+32]
    letters=[]
    for c in b[8:12]:
        if not c: continue
        digits='%02X' % c
        if not digits.isdigit() or not 65<=int(digits)<=90: letters=[];break
        letters.append(chr(int(digits)))
    material=''.join(letters) or None
    return chip_metadata('elegoo',uid,'Elegoo',material,[b[16:19].hex().upper()],
                         code=material or b[8:12].hex().upper(),diameter=int.from_bytes(b[28:30],'big')/100.,
                         weight=int.from_bytes(b[30:32],'big'),low=int.from_bytes(b[20:22],'big'),
                         high=int.from_bytes(b[22:24],'big'))


def decode_tigertag(uid,data):
    # Published memory map begins at page 4; do not scan arbitrary NDEF content.
    b=data[16:]
    if len(b)<44 or b[12]!=0x8E or b[:4] not in (bytes.fromhex('5BF59264'),bytes.fromhex('BC0FCB97')):
        raise ValueError('Invalid TigerTag block')
    count={252:2,24:3,145:3}.get(b[11],{252:2,24:3,145:3}.get(b[10],1))
    code='%04X:%04X:%08X' % (int.from_bytes(b[14:16],'big'),int.from_bytes(b[8:10],'big'),int.from_bytes(b[4:8],'big'))
    scale={10:.001,21:1,35:1000}.get(b[23])
    weight=int.from_bytes(b[20:23],'big')*scale if scale is not None else None
    result=chip_metadata('tigertag',uid,'TigerTag',None,[b[o:o+3].hex().upper() for o in (16,36,40)[:count]],
                         code=code,variant=b[10:12].hex().upper(),alpha=b[19],
                         diameter={0x38:1.75,0xDD:2.85}.get(b[13]),weight=weight or None,
                         low=int.from_bytes(b[24:26],'big') or None, high=int.from_bytes(b[26:28],'big') or None,bed=b[31])
    index,count=b[39]>>4,b[39]&15
    if count and index>count:raise ValueError('Invalid TigerTag index/count')
    # Timestamp is a pairing hint, not a globally unique roll identity. Preserve
    # it for diagnosis; never automatically merge same-second factory batches.
    result.update(twin_id=int.from_bytes(b[32:36],'big'),tag_index=index,tag_count=count)
    return result


def ndef_records(data):
    """Bounded Type 2 TLV + unchunked NDEF MIME records. Never follows a URL."""
    pos=16;messages=[]
    while pos<len(data):
        kind=data[pos];pos+=1
        if kind==0:continue
        if kind==254:break
        if kind not in (1,2,3,253) or pos>=len(data):raise ValueError('Invalid TLV')
        size=data[pos];pos+=1
        if size==255:
            if pos+2>len(data):raise ValueError('Short TLV size')
            size=int.from_bytes(data[pos:pos+2],'big');pos+=2
        end=pos+size
        if end>len(data):raise ValueError('Truncated TLV')
        if kind==3:messages.append(bytes(data[pos:end]))
        pos=end
    if len(messages)!=1:raise ValueError('Expected one NDEF message')
    msg=messages[0];pos=0;records=[];ended=False
    while pos<len(msg):
        if len(records)>=16 or ended or pos+3>len(msg):raise ValueError('Invalid NDEF framing')
        header,typelen=msg[pos:pos+2];pos+=2
        if bool(header&128)!=(len(records)==0) or header&32:raise ValueError('Chunked or misframed NDEF')
        sizebytes=1 if header&16 else 4
        if pos+sizebytes>len(msg):raise ValueError('Short NDEF length')
        size=int.from_bytes(msg[pos:pos+sizebytes],'big');pos+=sizebytes
        idlen=0
        if header&8:
            if pos>=len(msg):raise ValueError('Short NDEF ID')
            idlen=msg[pos];pos+=1
        if pos+typelen+idlen+size>len(msg):raise ValueError('Truncated NDEF record')
        typ=msg[pos:pos+typelen];pos+=typelen+idlen
        payload=msg[pos:pos+size];pos+=size
        records.append((typ.decode('ascii').lower() if header&7==2 else '',payload))
        ended=bool(header&64)
    if not ended:raise ValueError('Missing NDEF end')
    return records


def decode_json_tag(uid,payload):
    import json
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:raise ValueError('Duplicate JSON field')
            result[k]=v
        return result
    data=json.loads(payload,object_pairs_hook=pairs)
    if not isinstance(data,dict) or 'protocol' in data:raise ValueError('Not generic filament JSON')
    def first(*names):return next((data[n] for n in names if data.get(n) not in (None,'')),None)
    def color(value):
        if not isinstance(value,str):return None
        s=value.lstrip('#').upper()
        return s[:6] if len(s) in (6,8) and all(c in '0123456789ABCDEF' for c in s) else None
    colors=[color(first('color_hex','color','colour','hex'))]
    extras=data.get('additional_color_hexes',[])
    if not isinstance(extras,list) or len(extras)>5:raise ValueError('Invalid extra colors')
    colors=[c for c in colors+[color(c) for c in extras] if c][:5]
    material=first('type','material','material_type')
    if not material and not colors:raise ValueError('No filament fields')
    return chip_metadata('generic-ndef',uid,first('manufacturer','brand','vendor','make') or 'Unknown',
        material,colors,variant=first('subtype','sub_type','variant') or 'default',
        diameter=first('diameter','diameter_mm'),weight=first('weight','weight_g','net_weight'),
        low=first('min_temp','nozzle_min_temp','hotend_min_temp','temp_min'),
        high=first('max_temp','nozzle_max_temp','hotend_max_temp','temp_max'),
        bed=first('bed_temp','bed_max_temp','bed_min_temp','bed'))


def decode_opentag(uid,b):
    version=int.from_bytes(b[:2],'big')//1000
    if version not in (0,1,2) or len(b)<(160 if version==2 else 98):raise ValueError('Unsupported/truncated OpenTag3D')
    b=b.ljust(224,b'\0')
    if version==2: maker,cols,dia,weight,temp,low,high,bed=12,(60,64,68,72),140,158,144,145,146,148
    else: maker,cols,dia,weight,temp,low,high,bed=27,(75,80,84,88),92,94,96,180,181,97
    def txt(offset,size):return b[offset:offset+size].rstrip(b'\0').decode('ascii').strip()
    material=txt(2,5);variant=txt(7,5) or 'default'
    colors=[b[o:o+3].hex().upper() for i,o in enumerate(cols) if i==0 or any(b[o:o+4])]
    return chip_metadata('opentag',uid,txt(maker,16) or 'Unknown',material or None,colors,variant=variant,
        alpha=b[cols[0]+3],diameter=int.from_bytes(b[dia:dia+2],'big')/1000. or None,
        weight=int.from_bytes(b[weight:weight+2],'big') or None,
        low=(b[low] or b[temp])*5 or None,high=(b[high] or b[temp])*5 or None,bed=b[bed]*5)


def cbor_at(data,offset=0):
    """Bounded CBOR subset; depth, item count and bytes bounded."""
    count=[0]
    def read(pos,depth):
        count[0]+=1
        if depth>8 or count[0]>256 or pos>=len(data):raise ValueError('CBOR bound exceeded')
        h=data[pos];pos+=1;major=h>>5;info=h&31
        width={24:1,25:2,26:4,27:8}.get(info,0)
        indefinite=info==31 and major in (4,5)
        if info>=24 and not width and not indefinite:raise ValueError('Unsupported CBOR encoding')
        if pos+width>len(data):raise ValueError('Short CBOR value')
        n=int.from_bytes(data[pos:pos+width],'big') if width else info
        raw=data[pos:pos+width];pos+=width
        if major==0:return n,pos
        if major==1:return -1-n,pos
        if major in (2,3):
            if n>len(data)-pos:raise ValueError('Short CBOR string')
            value=data[pos:pos+n];return (value.decode('utf8') if major==3 else bytes(value)),pos+n
        if major in (4,5):
            if n>128:raise ValueError('CBOR collection too large')
            values=[]
            if indefinite:
                while True:
                    if pos>=len(data) or len(values)>=256:raise ValueError('Unterminated CBOR collection')
                    if data[pos]==255:pos+=1;break
                    value,pos=read(pos,depth+1);values.append(value)
                if major==5 and len(values)%2:raise ValueError('Odd CBOR map')
            else:
                for _ in range(n*(2 if major==5 else 1)):
                    value,pos=read(pos,depth+1);values.append(value)
            if major==4:return values,pos
            result={}
            for k,v in zip(values[::2],values[1::2]):
                if type(k) not in (int,str) or k in result:raise ValueError('Invalid/duplicate CBOR key')
                result[k]=v
            return result,pos
        if major==7:
            if info in (20,21,22):return {20:False,21:True,22:None}[info],pos
            if info in (25,26,27):return struct.unpack({25:'>e',26:'>f',27:'>d'}[info],raw)[0],pos
        raise ValueError('Unsupported CBOR value')
    return read(offset,0)


def decode_openprinttag(uid,b):
    meta,end=cbor_at(b)
    if not isinstance(meta,dict):raise ValueError('Invalid OpenPrintTag meta')
    start=meta.get(0,end)
    if type(start)!=int or not end<=start<len(b):raise ValueError('Invalid OpenPrintTag region')
    main,_=cbor_at(b,start)
    if not isinstance(main,dict):raise ValueError('Invalid OpenPrintTag main')
    colors=[main[k] for k in (19,20,21,22,23,24) if k in main]
    if any(not isinstance(c,bytes) or len(c) not in (3,4) for c in colors):raise ValueError('Invalid OpenPrintTag color')
    return chip_metadata('openprinttag',uid,main.get(11) or 'Unknown',main.get(52) or main.get(10),
        [c[:3].hex().upper() for c in colors[:5]],alpha=colors[0][3] if colors and len(colors[0])==4 else 255,
        name=main.get(10),diameter=main.get(30),weight=main.get(16),low=main.get(34),high=main.get(35),bed=main.get(38))


def decode_pages(uid,data,enabled):
    if len(uid)!=7 or len(data)<32 or data[:3]+data[4:8]!=bytes(uid):raise ValueError('Changed Type 2 UID')
    matches=[]
    for kind,decoder in (('anycubic',decode_anycubic),('elegoo',decode_elegoo),('tigertag',decode_tigertag)):
        if kind in enabled:
            try:matches.append(decoder(uid,data))
            except (ValueError,IndexError,TypeError):pass
    try:records=ndef_records(data)
    except (ValueError,UnicodeError):records=[]
    for mime,payload in records:
        pair={'application/json':('generic-ndef',decode_json_tag),
              'application/opentag3d':('opentag',decode_opentag),
              'application/vnd.openprinttag':('openprinttag',decode_openprinttag)}.get(mime)
        if pair and pair[0] in enabled:
            try:matches.append(pair[1](uid,payload))
            except (ValueError,TypeError,IndexError,RecursionError):pass
    if len(matches)!=1:raise ValueError('No unique supported page payload')
    return matches[0]


def read_pages(reader,fm,uid,activate,enabled):
    data=bytearray();target=32
    # <= 222 user pages on NTAG216. Use READ only; trust bounded CC capacity,
    # never probe nonexistent pages or consume lock/config bytes as payload.
    for page in range(0,224,4):
        if getattr(reader,P+'stop_event').is_set():raise ValueError('Reader stopping')
        r=getattr(reader,P+'reader_a_m1_block_read')(page)
        if r.err_code!=fm.FM175XX_OK or len(r.out_param)!=16:raise ValueError('Type 2 page unavailable')
        data.extend(r.out_param)
        if page==0:
            target=16+data[14]*8 if data[12]==0xE1 and data[13]>>4==1 and data[15]>>4==0 else 128
            if not 32<=target<=888:raise ValueError('Unsupported Type 2 capacity')
        if page==4 and data[16:20] in (b'\x7b\0\x64\0',b'\x7b\0\x65\0'):
            target=128
        if len(data)>=target:break
    if activate()!=fm.FM175XX_OK or selected_uid(getattr(reader,P+'picc_a'))!=list(uid):raise ValueError('Type 2 tag changed')
    return decode_pages(uid,bytes(data[:target]),enabled)


def selected_uid(picc):
    count = {0: 1, 0x40: 2, 0x80: 3}.get(picc.ATQA[0] & 0xC0)
    if count is None or picc.CASCADE_LEVEL != count - 1:
        return None
    uid = []
    for i in range(count):
        block = list(picc.UID[i*4:i*4+4])
        if len(block) != 4 or any(type(v) is not int or not 0 <= v <= 255 for v in block):
            return None
        if picc.BCC[i] != block[0] ^ block[1] ^ block[2] ^ block[3]:
            return None
        more = i < count - 1
        if bool(picc.SAK[i] & 4) != more or (more and block[0] != 0x88):
            return None
        uid.extend(block[1:] if more else block)
    return uid if any(uid) and uid[0] != 8 else None


class MemoryUidBridge:
    def __init__(self, enqueue):
        self.enqueue = enqueue
        self.epoch = uuid.uuid4().hex
        self.sequence = 0
        self.channels = {str(i): {'state': 'unknown', 'uid': None} for i in range(4)}
        self.local = threading.local()
        self.lock = threading.RLock()
        self.reader = None
        self.active = False
        self.generation = 0

    def attach(self, reader, *, source_path, allowed_sha256, read_op, clear_op, ok=0, payload_reader=None, page_reader=None):
        if self.active or getattr(reader, '_tracker_uid_owner', None) is not None:
            raise ValueError('Already wrapped')
        if hashlib.sha256(Path(source_path).read_bytes()).hexdigest() not in allowed_sha256:
            raise ValueError('Unsupported driver hash')
        names = [P+'select_channel', P+'reader_a_activate', P+'card_info_deal_cb',
                 'register_cb_2_card_info_deal']
        if payload_reader:
            names.append(P+'reader_a_m1_read_all_data')
        if any(not hasattr(reader, n) or (n != P+'card_info_deal_cb' and not callable(getattr(reader, n))) for n in names):
            raise ValueError('Driver interface unavailable')
        self.original = {n: getattr(reader, n) for n in names}
        self.instance_original = {n: (n in vars(reader), vars(reader).get(n)) for n in names}
        self.stock_callback = self.original[P+'card_info_deal_cb']
        self.reader = reader
        def select(channel):
            result = self.original[P+'select_channel'](channel)
            self.local.channel = channel
            self.local.seen = set()
            self.local.tag = None
            self.local.tag_error = None
            self.local.payload_attempted = False
            return result
        def activate():
            result = self.original[P+'reader_a_activate']()
            if result == ok:
                try:
                    uid = selected_uid(getattr(reader, P+'picc_a'))
                    if uid and hasattr(self.local, 'seen'):
                        self.local.seen.add(bytes(uid).hex().upper())
                        picc = getattr(reader, P+'picc_a')
                        if (self.active and page_reader and len(uid) == 7 and picc.SAK[picc.CASCADE_LEVEL] == 0
                                and not self.local.payload_attempted and getattr(reader, P+'self_test_stage', None) != 1):
                            self.local.payload_attempted = True
                            try:
                                self.local.tag = page_reader(uid, activate)
                            except Exception:
                                self.local.tag_error = 'metadata_unavailable'
                except Exception:
                    # An observer must not turn a successful stock scan into a failure.
                    pass
            return result
        def callback(channel, operation, result, card_type, data):
            # Stock receives EXACT original arguments, including authentication failure.
            answer = self.stock_callback(channel, operation, result, card_type, data) if self.stock_callback else None
            if type(channel) is int and 0 <= channel < 4:
                if operation == clear_op:
                    self._publish(channel, 'absent', None)
                elif operation == read_op:
                    seen = getattr(self.local, 'seen', set()) if getattr(self.local, 'channel', None)==channel else set()
                    if len(seen)==1:
                        uid = next(iter(seen))
                        tag = getattr(self.local, 'tag', None)
                        self._publish(channel, 'present', uid,
                                      tag=tag if tag and tag['uid'] == uid else None,
                                      tag_error=getattr(self.local, 'tag_error', None))
                    else:
                        self._publish(channel, 'conflict' if len(seen)>1 else 'unreadable', None)
            self.local.seen = set()
            return answer
        def register(cb):
            if not callable(cb):
                return self.original['register_cb_2_card_info_deal'](cb)
            self.stock_callback = cb
            return self.original['register_cb_2_card_info_deal'](callback)
        self.wrappers = dict(zip(names, [select, activate, callback, register]))
        if payload_reader:
            def read_all(*args, **kwargs):
                result = self.original[P+'reader_a_m1_read_all_data'](*args, **kwargs)
                if (self.active and result.err_code != ok
                        and not getattr(self.local, 'payload_attempted', False)
                        and getattr(reader, P+'self_test_stage', None) != 1):
                    self.local.payload_attempted = True
                    try:
                        uid = selected_uid(getattr(reader, P+'picc_a'))
                        self.local.tag = payload_reader(uid, activate) if uid else None
                    except Exception:
                        self.local.tag = None
                        self.local.tag_error = 'metadata_unavailable'
                return result  # Stock parser receives its own result, never Bambu bytes.
            self.wrappers[P+'reader_a_m1_read_all_data'] = read_all
        reader._tracker_uid_owner = self
        for n, value in self.wrappers.items(): setattr(reader, n, value)
        self.active = True
        self.generation += 1

    def _publish(self, channel, state, uid, *, tag=None, tag_error=None):
        with self.lock:
            if not self.active: return
            generation = self.generation
            self.sequence += 1
            seq = self.sequence
            observed_at = time.monotonic()
        def apply(_eventtime=0):
            with self.lock:
                if not self.active or generation != self.generation: return
                if seq <= self.channels[str(channel)].get('sequence', 0): return
                self.channels[str(channel)] = {'state': state, 'uid': uid, 'sequence': seq, 'observed_at': observed_at}
                if tag is not None:
                    self.channels[str(channel)]['tag'] = copy.deepcopy(tag)
                if tag_error:
                    self.channels[str(channel)]['tag_error'] = tag_error
        try:
            self.enqueue(apply)
        except Exception:
            # No propagation into the stock driver's thread. Invalidate cached state.
            with self.lock:
                self.generation += 1
                self.channels = {str(i): {'state':'unknown','uid':None} for i in range(4)}

    def suspend(self):
        # Do not replace hooks while the stock thread may still be executing.
        # Hooks remain transparent pass-through until the Klipper process exits.
        with self.lock:
            self.active = False
            self.generation += 1
            self.channels = {str(i): {'state': 'unknown', 'uid': None} for i in range(4)}

    def detach(self):
        if not self.active: return
        r=self.reader
        if any(getattr(r,n) is not wrapper for n,wrapper in self.wrappers.items()):
            raise ValueError('Another component replaced a hook; restart required')
        with self.lock:
            self.active=False; self.generation+=1
            self.channels={str(i):{'state':'unknown','uid':None} for i in range(4)}
        for n,(existed,value) in self.instance_original.items():
            if n == P+'card_info_deal_cb': setattr(r,n,self.stock_callback)
            elif existed: setattr(r,n,value)
            else: delattr(r,n)
        del r._tracker_uid_owner

    def get_status(self):
        with self.lock:
            return copy.deepcopy({'epoch':self.epoch,'sequence':self.sequence,'channels':self.channels})


# Exact raw source hashes from the pinned firmware corpus; no permissive override.
SUPPORTED_DRIVERS = {'c118a0ff0077d789a558f738bead5cf8e10e28a0a57bb693ba47212303c6ece6': '1.3.0.168', '68ec97fd4dab74a1fb3690f6f2c4e889abac1c2dc9eedaebb43dab2657ddd392': '2.0.0.205', 'ce7363f8b512e5474d18bd57cdf0660e6e2df57dc256e22f743b3b28c1b70be8': '2.1.0.157'}


def _validate_methods(reader, driver_module, source, bambu=False, pages=False):
    if type(reader) is not driver_module.FM175XXReader:
        raise ValueError('Unexpected reader class')
    # Check the loaded code against the approved source, not just the file on disk.
    compiled = compile(source.read_bytes(), str(source), 'exec')
    code_type = type(compiled)
    klass = next(c for c in compiled.co_consts if isinstance(c, code_type) and c.co_name=='FM175XXReader')
    expected = {c.co_name:c for c in klass.co_consts if isinstance(c,code_type)}
    names = [P+'select_channel',P+'reader_a_activate','register_cb_2_card_info_deal']
    if bambu:
        names += [P+n for n in ('reader_a_m1_read_all_data', 'reader_a_mifare_auth', 'reader_a_m1_block_read')]
    elif pages:
        names.append(P+'reader_a_m1_block_read')
    for name in names:
        fn = getattr(reader,name,None)
        short = name.replace(P,'__',1) if name.startswith(P) else name
        if name in vars(reader) or not inspect.ismethod(fn) or fn.__self__ is not reader:
            raise ValueError('Reader has an existing hook: '+name)
        code=fn.__func__.__code__
        wanted=expected.get(short)
        if wanted is None or code.co_code!=wanted.co_code or code.co_consts!=wanted.co_consts:
            raise ValueError('Loaded reader differs from approved source: '+name)


class TrackerUid:
    def __init__(self, config):
        self.printer=config.get_printer()
        self.reactor=self.printer.get_reactor()
        self.enabled=config.getboolean('enabled', True)
        self.stale_after=config.getfloat('stale_after', 300., minval=1.)
        self.bridge=MemoryUidBridge(self.reactor.register_async_callback)
        self.state='disabled' if not self.enabled else 'waiting'
        self.reason=''
        self.driver_version=None
        self.connected=False
        self.bambu_enabled=config.getboolean('bambu_read_enabled', False)
        self.qidi_enabled=config.getboolean('qidi_read_enabled', False)
        self.anycubic_enabled=config.getboolean('anycubic_read_enabled', False)
        self.creality_enabled=config.getboolean('creality_read_enabled', False)
        self.page_formats={name for name in ('elegoo','tigertag','generic-ndef','opentag','openprinttag')
                           if config.getboolean(name.replace('-','_')+'_read_enabled',False)}
        if self.anycubic_enabled:self.page_formats.add('anycubic')
        self.creality_keys=(None,None)
        if self.creality_enabled:
            self.creality_keys=configured_creality_keys(config)

        self.printer.register_event_handler('klippy:connect', self._connect)
        self.printer.register_event_handler('klippy:ready', self._ready)
        for event in ('klippy:shutdown','klippy:disconnect','klippy:connect_error','gcode:request_restart'):
            self.printer.register_event_handler(event,self._stop)
        self.api_available=False
        try:
            self.printer.lookup_object('webhooks').register_endpoint('tracker_uid/status',self._status_request)
            self.api_available=True
        except Exception as exc:
            # This optional observer must not block stock startup if its API
            # cannot be registered. Do not hook the reader in that case.
            self.state='unavailable';self.reason='UID API unavailable: '+str(exc)
            logging.warning('tracker_uid disabled: %s',self.reason)

    def _connect(self):
        if not self.enabled or self.connected or not self.api_available:
            return
        self.connected=True
        try:
            reader=self.printer.lookup_object('fm175xx_reader',None)
            if reader is None:raise ValueError('RFID reader unavailable')
            module=sys.modules[type(reader).__module__]
            source=Path(inspect.getsourcefile(module)).resolve()
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            if digest not in SUPPORTED_DRIVERS:raise ValueError('Unsupported driver hash')
            _validate_methods(reader,module,source,self.bambu_enabled or self.qidi_enabled or self.creality_enabled,bool(self.page_formats))
            def classic(uid, activate):
                for enabled, decode in ((self.bambu_enabled, read_bambu), (self.qidi_enabled, read_qidi),
                                        (self.creality_enabled, lambda r,m,u,a: read_creality(r,m,u,a,*self.creality_keys))):
                    if enabled:
                        try:
                            result = decode(reader,module,uid,activate)
                            if result is not None:return result
                        except (ValueError, TypeError, IndexError):
                            pass
                raise ValueError('No supported Classic payload')
            self.bridge.attach(reader,source_path=source,allowed_sha256=SUPPORTED_DRIVERS,
                               read_op=module.FM175XX_CARD_INFO_READ,
                               clear_op=module.FM175XX_CARD_INFO_CLEAR,ok=module.FM175XX_OK,
                               payload_reader=classic if self.bambu_enabled or self.qidi_enabled or self.creality_enabled else None,
                               page_reader=(lambda uid, activate: read_pages(reader,module,uid,activate,self.page_formats))
                               if self.page_formats else None)
            self.driver_version=SUPPORTED_DRIVERS[digest]
            self.state='attached'
        except Exception as exc:
            self.state='unavailable';self.reason=str(exc)
            logging.warning('tracker_uid disabled: %s',exc)

    def _ready(self):
        if self.state=='attached':self.state='ready'

    def _stop(self,*args):
        self.bridge.suspend()
        self.state='stopped'
        self.reason='Klipper stopped; restart required'

    def get_status(self,eventtime=None):
        if self.bridge.active and any(getattr(self.bridge.reader,n,None) is not wrapper
                                      for n,wrapper in self.bridge.wrappers.items()):
            self.bridge.suspend()
            self.state='unavailable'
            self.reason='Reader hook changed; restart required'
        status=self.bridge.get_status()
        now=time.monotonic()
        for channel in status['channels'].values():
            observed=channel.pop('observed_at',None)
            channel['age_seconds']=max(0.,now-observed) if observed is not None else None
            if observed is not None and now-observed>self.stale_after:
                channel['state']='stale';channel['uid']=None;channel.pop('tag',None)
            channel['uid_length'] = len(channel['uid'])//2 if channel['uid'] else 0
        status.update(schema_version=1, module_version='0.6.0-auto-lookup-bench',state=self.state,
                      reason=self.reason,driver_version=self.driver_version)
        return status

    def _status_request(self, request):
        request.send(self.get_status())


def load_config(config):
    return TrackerUid(config)
