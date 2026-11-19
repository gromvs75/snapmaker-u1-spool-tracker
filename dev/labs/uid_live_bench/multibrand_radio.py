"""NO HARDWARE. QIDI Classic and Anycubic Type 2 alongside Bambu RF fixtures."""
from pathlib import Path
from types import SimpleNamespace
from .bambu_radio import BambuRadio
from .bench_radio import P


class MultiRadio(BambuRadio):
    def __init__(self, config):
        super().__init__(config)
        from . import fm175xx_reader
        self.fm = fm175xx_reader
        root=Path(config.get_printer().get_start_args()['config_file']).resolve().parents[2]
        self.dumps.update({p.stem:p.read_bytes() for p in (root/'other-dumps').glob('*.bin')})
        self.short_page=False

    def fault(self, request):
        mode=request.get_str('mode')
        if mode in ('page','short_page'):
            self.read_fault=20 if mode=='page' else None
            self.short_page=mode=='short_page'
            request.send({'fault':mode});return
        self.short_page=False
        super().fault(request)

    def command(self, cmd):
        uid=bytes(self.cards[self.channel][1]).hex().upper()
        if len(uid)==8:return super().command(cmd)
        fm=self.fm;sent=list(cmd.send_buff[:cmd.bytes_to_send]);self.commands.append(sent)
        if cmd.cmd!=fm.FM175XX_CMD_TRANSCEIVE or sent[0]!=0x30:
            raise AssertionError('Only READ is permitted for Type 2 tags')
        page=sent[1];data=self.dumps[uid];block=data[page*4:page*4+16]
        if page==self.read_fault:return SimpleNamespace(err_code=fm.FM175XX_CARD_READ_ERR)
        if self.short_page:block=block[:12]
        return SimpleNamespace(err_code=0,out_param=SimpleNamespace(bytes_recved=len(block),recv_buff=list(block)))


def load_config(config):return MultiRadio(config)
