"""Synthetic RF data only. AES ciphertext/key bytes checked with OpenSSL CLI.

These are not factory dumps. Full-page public fixtures stay in output/research.
"""
import json
import struct

MASTER='000102030405060708090a0b0c0d0e0f'
PAYLOAD_KEY='2b7e151628aed2a6abf7158809cf4f3c'
CIPHER=bytes.fromhex('69dd7c6aeaa35b71a841d276c7dcbae5a4377241cb2adcffc80e7a9428b5a9fae54192b5e33ad09df6e119b4a9370da5')
KEYS={'4024C26A':'dddf0f7cb588','4124C26A':'9f74c784a696'}
KINDS=('creality','elegoo','tigertag','generic-ndef','opentag','openprinttag')


def uid_for(kind,side=0):
    return ('4024C26A','4124C26A')[side] if kind=='creality' else '04%02X22334455%02X' % (KINDS.index(kind),side+1)


def pages(uid,size=512):
    b=bytearray(size);u=bytes.fromhex(uid)
    b[:3]=u[:3];b[3]=0x88^u[0]^u[1]^u[2];b[4:8]=u[3:];b[8]=u[3]^u[4]^u[5]^u[6]
    b[12:16]=bytes([0xE1,0x10,(size-16)//8,0])
    return b


def ndef(uid,mime,payload):
    b=pages(uid);mime=mime.encode();msg=bytes([0xC2,len(mime)])+len(payload).to_bytes(4,'big')+mime+payload
    tlv=b'\x03'+(bytes([len(msg)]) if len(msg)<255 else b'\xff'+len(msg).to_bytes(2,'big'))+msg+b'\xfe'
    assert len(tlv)<=len(b)-16;b[16:16+len(tlv)]=tlv
    return b


def cbor(value):
    def head(major,n):
        if n<24:return bytes([major*32+n])
        if n<256:return bytes([major*32+24,n])
        return bytes([major*32+25])+n.to_bytes(2,'big')
    if isinstance(value,str):
        b=value.encode();return head(3,len(b))+b
    if isinstance(value,bytes):return head(2,len(value))+value
    if isinstance(value,float):return b'\xfa'+struct.pack('>f',value)
    if isinstance(value,int):return head(0,value)
    if isinstance(value,dict):return head(5,len(value))+b''.join(cbor(k)+cbor(v) for k,v in value.items())
    raise TypeError(value)


def fixture(kind,side=0):
    uid=uid_for(kind,side);b=pages(uid) if kind!='creality' else bytearray(1024)
    if kind=='creality':
        b[:4]=bytes.fromhex(uid);b[64:112]=CIPHER;b[122:128]=bytes.fromhex(KEYS[uid]);return b
    if kind=='elegoo':
        b[64:72]=bytes.fromhex('36EEEEEEEE000000');b[72:76]=bytes.fromhex('00807665')
        b[80:84]=bytes.fromhex('09C299FF');b[84:88]=struct.pack('>HH',190,230);b[92:96]=struct.pack('>HH',175,1000)
    elif kind=='tigertag':
        b[16:20]=bytes.fromhex('5BF59264');b[20:24]=(123).to_bytes(4,'big');b[24:26]=(321).to_bytes(2,'big')
        b[28]=0x8E;b[39]=21;b[48:52]=(12345678).to_bytes(4,'big');b[55]=((side+1)<<4)|2
        b[29]=0x38;b[30:32]=(456).to_bytes(2,'big');b[32:36]=bytes.fromhex('ABCDEF80')
        b[36:39]=(1000).to_bytes(3,'big');b[40:44]=struct.pack('>HH',190,230);b[47]=60
    elif kind=='generic-ndef':
        return ndef(uid,'application/json',json.dumps(dict(brand='Bench filament',material='PETG',color='#C12E1F',
                    diameter=1.75,weight=1000,min_temp=220,max_temp=260,remaining_weight=999,spool_id=123)).encode())
    elif kind=='opentag':
        p=bytearray(224);p[:2]=(2000).to_bytes(2,'big');p[2:5]=b'PLA';p[12:26]=b'Bench filament'
        p[60:64]=bytes.fromhex('112233FF');p[140:142]=(1750).to_bytes(2,'big');p[158:160]=(1000).to_bytes(2,'big')
        p[145]=38;p[146]=46;p[148]=12;return ndef(uid,'application/opentag3d',p)
    else:
        return ndef(uid,'application/vnd.openprinttag',cbor({})+cbor({10:'PLA Bench',11:'Bench filament',52:'PLA',
                    16:1000,19:bytes.fromhex('778899FF'),30:1.75,34:190,35:230,38:60,17:998})+cbor({}))
    return b
