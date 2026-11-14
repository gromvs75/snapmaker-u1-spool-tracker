"""Synthetic transition controls, ONLY in marked no-hardware Klipper bench."""
from .bench_motion import BenchMotion
from .barrier_protocol import Source


class Transition(BenchMotion):
    def __init__(self,config):
        self.pending=[];self.trace=[];self.barrier_source=Source()
        super().__init__(config)
    def event(self,req):
        action=req.get_str('action')
        if action.startswith('barrier_'):
            try:
                if action=='barrier_start':
                    self.barrier_source=Source();result={'epoch':self.barrier_source.epoch}
                elif action=='barrier_packet':
                    result=self.barrier_source.packet(req.get_int('head'),req.get_float('start'),req.get_float('end'),req.get_float('length'),bool(req.get_int('delayed',0)))
                    if req.get_int('delayed',0):result={'queued':True}
                elif action=='barrier_flush':result={'packets':self.barrier_source.flush()}
                elif action=='barrier_seal':result=self.barrier_source.barrier(req.get_str('id'),req.get_float('fence'))
                else:raise ValueError('Unknown barrier control')
                req.send({'value':result})
            except ValueError as exc:req.send({'rejected':str(exc)})
            return
        if action in ('sample','queue_sample'):
            head=req.get_int('head');length=req.get_float('length');stamp=req.get_float('stamp')
            counter=req.get_float('counter',length)
            self.stats.filament_used+=counter
            sample=dict(head=head,length=length,stamp=stamp,counter=counter)
            self.trace.append(dict(kind='command',**sample,state=self.stats.state))
            if action=='queue_sample':self.pending.append(sample)
            else:self.emit(sample)
        elif action=='flush':
            for sample in self.pending:self.emit(sample)
            self.pending=[]
        elif action=='service_pause':
            right=self.printer.lookup_object('filament_feed right').value
            right['extruder3']=dict(right['extruder3'],filament_detected=False)
            self.trace.append(dict(kind='runout',head=3,fence=10))
            self.stats.note_pause()
            task=self.printer.lookup_object('print_task_config').value
            task['extruder_map_table']=[0,1,2,1];task['extruders_replenished']=[0,1,2,1]
            self.trace.append(dict(kind='status_boundary',state='paused',fence=10))
        elif action=='service_resume':
            self.stats.note_start()
            self.trace.append(dict(kind='status_boundary',state='printing',fence=20))
        else:return super().event(req)
        req.send({'ok':True})
    def emit(self,sample):
        self.trace.append(dict(kind='delivery',**sample,state=self.stats.state))
        for conn,template in list(self.clients[sample['head']]):
            if not conn.is_closed():
                message=dict(template);message['params']={'data':[[sample['stamp'],1,sample['length'],0,[0,0,0],[1,0,0]]]};conn.send(message)
    def get_status(self,eventtime):
        return dict(super().get_status(eventtime),trace=self.trace,clock='synthetic-command-clock')


def load_config(config):return Transition(config)
