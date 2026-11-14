"""Synthetic motion only, for marked NO-HARDWARE Klipper process benches."""
from pathlib import Path

class Status:
    def __init__(self, value): self.value = value
    def get_status(self, eventtime): return self.value

class BenchMotion:
    def __init__(self, config):
        self.printer = p = config.get_printer()
        root = Path(p.get_start_args()['config_file']).resolve().parents[2]
        if not (root / '.tracker-uid-simulator.json').is_file():
            raise config.error('bench_motion requires marked simulator')
        self.clients = {i: [] for i in range(4)}
        self.stats = p.load_object(config, 'print_stats')
        wh = p.lookup_object('webhooks')
        for i in range(4):
            wh.register_mux_endpoint('motion_report/dump_trapq', 'name', 'extruder' if i == 0 else 'extruder%d' % i,
                                     lambda req, i=i: self.subscribe(req, i))
        wh.register_endpoint('bench_motion/event', self.event)
        channel = dict(module_exist=True, disable_auto=False, filament_detected=True)
        p.add_object('filament_feed left', Status({'extruder0': channel, 'extruder1': channel}))
        p.add_object('filament_feed right', Status({'extruder2': channel, 'extruder3': channel}))
        p.add_object('filament_detect', Status({'state': [0]*4, 'info': [{'CARD_UID': 0} for _ in range(4)]}))
        p.add_object('print_task_config', Status({'extruder_map_table': [0,1,2,3], 'extruders_replenished': [0,1,2,3]}))
    def subscribe(self, req, head):
        self.clients[head].append((req.get_client_connection(), req.get_dict('response_template', {})))
        req.send({'header': ['time','duration','velocity','acceleration','position','direction']})
    def event(self, req):
        action = req.get_str('action')
        if action == 'start':
            self.stats.set_current_file(req.get_str('filename')); self.stats.note_start()
        elif action == 'motion':
            head = req.get_int('head'); length = req.get_float('length'); stamp = req.get_float('stamp')
            self.stats.filament_used += length
            for conn, template in list(self.clients[head]):
                if conn.is_closed(): continue
                message = dict(template); message['params'] = {'data': [[stamp,1,length,0,[0,0,0],[1,0,0]]]}
                conn.send(message)
        elif action == 'pause': self.stats.note_pause()
        elif action == 'resume': self.stats.note_start()
        elif action == 'cancel': self.stats.note_cancel()
        elif action == 'complete': self.stats.note_complete()
        else: raise req.error('Unknown fixture action')
        req.send({'ok': True})
    def get_status(self, eventtime):
        return {'subscribers': [sum(not c.is_closed() for c,t in self.clients[i]) for i in range(4)]}

def load_config(config): return BenchMotion(config)
