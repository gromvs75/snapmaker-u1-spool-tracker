"""NO HARDWARE. Public Mifare dumps behind unchanged stock AUTH/READ methods.

SPI/GPIO/anticollision are simulated by BenchRadio. Sector keys are taken from
the dump trailers, independently of Tracker's HKDF implementation. Writes fail.
"""
from pathlib import Path
from types import SimpleNamespace
from .bench_radio import BenchRadio, P


class BambuRadio(BenchRadio):
    def __init__(self, config):
        super().__init__(config)
        global fm
        from . import fm175xx_reader as fm
        root = Path(config.get_printer().get_start_args()['config_file']).resolve().parents[2]
        self.dumps = {p.stem: p.read_bytes() for p in (root/'bambu-dumps').glob('*.bin')}
        if not self.dumps or any(len(b) != 1024 for b in self.dumps.values()):
            raise config.error('Bambu bench needs 1K dump files')
        self.auth_sector = None
        self.commands = []
        self.read_fault = None
        self.auth_fault = False
        r = self.reader
        # Undo only the old fixture's high-level stub. These three methods now
        # execute the actual, hash-checked official driver code.
        delattr(r, P+'reader_a_m1_read_all_data')
        setattr(r, P+'command_exe', self.command)
        setattr(r, P+'register_read', lambda register: 8 if self.auth_sector is not None else 0)
        self.cards = {0: ('mifare', list(bytes.fromhex(next(iter(self.dumps)))))}
        config.get_printer().lookup_object('webhooks').register_endpoint('bench_radio/fault', self.fault)

    def fault(self, request):
        mode = request.get_str('mode')
        if mode not in ('none', 'auth', 'identity_block'):
            raise request.error('Unknown bench fault')
        self.auth_fault = mode == 'auth'
        self.read_fault = 9 if mode == 'identity_block' else None
        request.send({'fault': mode})

    def command(self, cmd):
        uid = bytes(self.cards[self.channel][1]).hex().upper()
        data = self.dumps.get(uid, bytes(1024))
        sent = list(cmd.send_buff[:cmd.bytes_to_send])
        self.commands.append(sent)
        if cmd.cmd == fm.FM175XX_CMD_MF_AUTHENT and sent[0] in (0x60,0x61):
            sector = sent[1] // 4
            offset=(sector*4+3)*16+(10 if sent[0]==0x61 else 0)
            expected = data[offset:offset+6]
            success = (not self.auth_fault and bytes(sent[2:8]) == expected
                       and bytes(sent[8:12]).hex().upper() == uid)
            self.auth_sector = sector if success else None
            return SimpleNamespace(err_code=0 if success else fm.FM175XX_CARD_AUTH_ERR)
        if cmd.cmd == fm.FM175XX_CMD_TRANSCEIVE and sent[0] == 0x30:
            block = sent[1]
            if self.auth_sector != block//4 or block == self.read_fault:
                return SimpleNamespace(err_code=fm.FM175XX_CARD_READ_ERR)
            return SimpleNamespace(err_code=0, out_param=SimpleNamespace(
                bytes_recved=16, recv_buff=list(data[block*16:(block+1)*16])))
        raise AssertionError('Forbidden RF command in read-only Bambu bench: '+repr(sent))

    def get_status(self, eventtime):
        return dict(super().get_status(eventtime), rf_commands=len(self.commands),
                    write_commands=sum(bool(c) and c[0] not in (0x60, 0x61, 0x30) for c in self.commands))


def load_config(config):
    return BambuRadio(config)
