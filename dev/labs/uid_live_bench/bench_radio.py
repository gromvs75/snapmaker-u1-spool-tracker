"""NO HARDWARE: SPI/GPIO and RF reply fixture for a real Klippy process.

Never install this fixture on a printer. Original driver constructor, activation,
channel selection, callback registration and background scan loop execute.
"""
import sys
import re
import types
from pathlib import Path

P = '_FM175XXReader__'

class Pin:
    def request(self, **kw): pass
    def set_value(self, value): pass
    def release(self): pass

class Spi:
    def open(self, *args): pass
    def close(self): pass
    def xfer2(self, data): return [0]*len(data)

class BenchRadio:
    def __init__(self, config):
        printer=config.get_printer()
        root=Path(printer.get_start_args()['config_file']).resolve().parents[2]
        if not (root/'.tracker-uid-simulator.json').is_file():
            raise config.error('bench_radio requires marked simulator')
        sys.modules['spidev']=types.SimpleNamespace(SpiDev=Spi)
        sys.modules['gpiod']=types.SimpleNamespace(Chip=lambda name:types.SimpleNamespace(get_line=lambda n:Pin()),LINE_REQ_DIR_OUT=1)
        from . import fm175xx_reader as fm
        params=dict(soc_ch_1=2,soc_ch_2=3,extra_ch_1=0,extra_ch_2=1)
        fake_config=types.SimpleNamespace(get_printer=lambda:printer,getint=lambda k:params.get(k,0))
        self.reader=r=fm.FM175XXReader(fake_config)
        printer.add_object('fm175xx_reader',r)
        self.cards={0:('mifare',[4,17,34,51]),1:('ntag',[4,17,34,51,68,85,102])}
        self.channel=0
        self.events=[]
        self.print_job=None
        def select_obj(ch): self.channel=ch
        setattr(r,P+'select_fm175xx_obj',select_obj)
        for name in ('hard_reset','reader_a_init','set_carrier_wave','reader_a_halt'):
            setattr(r,P+name,lambda *a:0)
        setattr(r,P+'register_read',lambda *a:0)
        def wakeup():
            if self.channel not in self.cards:return fm.FM175XX_CARD_WAKEUP_ERR
            uid=self.cards[self.channel][1]
            getattr(r,P+'picc_a').ATQA[0]={4:0,7:0x40,10:0x80}[len(uid)]
            return 0
        def anticoll(level):
            uid=self.cards[self.channel][1]
            blocks=([uid] if len(uid)==4 else [[0x88,*uid[:3]],uid[3:]] if len(uid)==7 else [[0x88,*uid[:3]],[0x88,*uid[3:6]],uid[6:]])
            b=blocks[level];p=getattr(r,P+'picc_a')
            p.UID[level*4:level*4+4]=b;p.BCC[level]=b[0]^b[1]^b[2]^b[3]
            return 0
        def select(level):
            kind,uid=self.cards[self.channel]
            getattr(r,P+'picc_a').SAK[level]=4 if level<{4:0,7:1,10:2}[len(uid)] else (0 if kind=='ntag' else 8)
            return 0
        setattr(r,P+'reader_a_wakeup',wakeup)
        setattr(r,P+'reader_a_anticoll',anticoll)
        setattr(r,P+'reader_a_select',select)
        setattr(r,P+'reader_a_m1_read_all_data',lambda *a:types.SimpleNamespace(err_code=fm.FM175XX_CARD_AUTH_ERR,out_param=[]))
        printer.register_event_handler('klippy:ready',self.ready)
        # Upstream reader doesn't handle disconnect; our fixture must stop its thread.
        printer.register_event_handler('klippy:disconnect',getattr(r,P+'shutdown'))
        printer.lookup_object('webhooks').register_endpoint('bench_radio/scan',self.scan)
        printer.lookup_object('webhooks').register_endpoint('bench_radio/clear',self.clear)
        printer.lookup_object('webhooks').register_endpoint('bench_radio/set_tag',self.set_tag)
        printer.lookup_object('webhooks').register_endpoint('bench_radio/print_event',self.print_event)
    def print_event(self, request):
        self.print_job=request.get_dict('event')
        request.send({'stored':True})
    def set_tag(self, request):
        ch=request.get_int('channel')
        uid=request.get_str('uid')
        if ch not in range(4) or not re.fullmatch(r'(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{14}|[0-9a-fA-F]{20})',uid):
            raise request.error('Invalid fixture tag')
        if getattr(self.reader,P+'card_info_read_flag'):
            raise request.error('Wait for fixture scan to finish')
        self.cards[ch]=('ntag' if len(uid)==14 else 'mifare',list(bytes.fromhex(uid)))
        request.send({'configured':ch})
    def ready(self):
        self.reader.register_cb_2_card_info_deal(lambda *a:self.events.append(a[:4]))
    def scan(self, request):
        ch=request.get_int('channel',0)
        if ch not in self.cards:raise request.error('Configure a fixture tag first')
        self.reader.request_read_card_info(ch)
        request.send({'queued':ch})
    def clear(self,request):
        ch=request.get_int('channel',0)
        if ch not in range(4):raise request.error('Invalid channel')
        self.reader.request_clear_card_info(ch)
        request.send({'queued':ch})
    def get_status(self,eventtime):return {'stock_callbacks':self.events[-8:],'print_job':self.print_job}

def load_config(config):return BenchRadio(config)
