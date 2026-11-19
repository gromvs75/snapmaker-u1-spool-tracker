"""Read-only Moonraker transports and profile acquisition for the UID launcher.

No legacy Store/monitor or constant material defaults. Accounting remains in the
UID owner. The separate opt-in guard may issue a single verified pause request.
"""
import hashlib
import json
import math
import socket
import tempfile
import time
from urllib.parse import quote,urlencode,urlsplit,urlunsplit
from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler
from gcode import parse_u1_gcode_handle,parse_filament_parameters_handle
from tool_mapping import validate_mapping
from tracker_uid_runtime import PrinterWorkers,ModelInventoryStore,history_read_timeout
from tracker_uid_recorder import MotionStreamRecorder


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('Moonraker redirect refused')


class ReadOnlyMoonraker:
    def __init__(self,url):
        self.stop_event=None
        self.url=url.rstrip('/');self.opener=build_opener(ProxyHandler({}),NoRedirect())
    def check_stop(self):
        if self.stop_event is not None and self.stop_event.is_set():raise InterruptedError("Collectors stopping")
    def read(self,path,limit=1_000_000):
        self.check_stop()
        with self.opener.open(Request(self.url+path,method='GET'),timeout=2) as response:
            raw=response.read(limit+1)
        if len(raw)>limit:raise ValueError('Moonraker response too large')
        value=json.loads(raw)
        if not isinstance(value,dict) or 'error' in value or 'result' not in value:raise ValueError('Invalid Moonraker response')
        return value['result']
    def history(self):
        jobs=[]
        for start in range(0,500,50):
            page=self.read(f'/server/history/list?limit=50&start={start}&order=desc')
            if not isinstance(page.get('jobs'),list):raise ValueError('History unavailable')
            jobs.extend(page['jobs'])
            if len(page['jobs'])<50 or start+50>=page.get('count',0):break
        return jobs
    def status(self):
        return self.read('/printer/objects/query?print_stats&print_task_config&filament_feed%20left&filament_feed%20right&toolhead')['status']
    def monitor_status(self):
        return self.read('/printer/objects/query?print_stats&toolhead&display_status&virtual_sdcard')['status']
    def inspect(self,filename):
        if not isinstance(filename,str) or not filename or filename.startswith('/') or '..' in filename.split('/'):
            raise ValueError('Invalid G-code filename')
        path='/server/files/metadata?'+urlencode({'filename':filename})
        before=self.read(path);size=before.get('size');modified=before.get('modified')
        if type(size) is not int or not 0<size<=512*1024*1024 or type(modified) not in (float,int) or not math.isfinite(modified):
            raise ValueError('Unverifiable G-code metadata')
        digest=hashlib.sha256();received=0;deadline=time.monotonic()+8
        with tempfile.TemporaryFile() as file:
            with self.opener.open(Request(self.url+'/server/files/gcodes/'+quote(filename,safe='/'),method='GET'),timeout=2) as response:
                while True:
                    self.check_stop()
                    if time.monotonic()>deadline:raise TimeoutError('G-code verification deadline')
                    chunk=response.read(64*1024)
                    if not chunk:break
                    received+=len(chunk)
                    if received>size:raise ValueError('G-code changed during verification')
                    digest.update(chunk);file.write(chunk)
            after=self.read(path)
            if received!=size or any(before.get(k)!=after.get(k) for k in ('size','modified','slicer','filament_type','filament_weight')):
                raise ValueError('G-code changed during verification')
            weights=parse_u1_gcode_handle(file);params=parse_filament_parameters_handle(file)
            from tracker_uid_gcode_estimate import layer_estimates
            try:layers=layer_estimates(file);layer_error=None
            except (ValueError,UnicodeError) as exc:layers={};layer_error=str(exc)
            if not params or any(w>0 and i>=len(params) for i,w in enumerate(weights)):
                raise ValueError('Used tool material parameters unavailable')
            return dict(logical_weights=weights,parameters=params+[None]*(4-len(params)),filament_type=after.get('filament_type'),file_sha256=digest.hexdigest(),layers=layers,layer_error=layer_error,metadata={k:after.get(k) for k in ('slicer','filament_type','filament_weight')})


class MotionSocket:
    def __init__(self,url):
        import websocket
        self.transport=websocket
        u=urlsplit(url)
        target=urlunsplit(('wss' if u.scheme=='https' else 'ws',u.netloc,u.path.rstrip('/')+'/klippysocket','',''))
        self.ws=websocket.create_connection(target,timeout=2,http_proxy_host=None,redirect_limit=0)
        self.ws.settimeout(.5)
    def send(self,raw):self.ws.send(raw.decode() if isinstance(raw,bytes) else raw)
    def receive(self):
        try:raw=self.ws.recv()
        except self.transport.WebSocketTimeoutException as exc:raise socket.timeout() from exc
        if not raw:raise ConnectionError('Motion socket closed')
        if len(raw)>2_000_000:raise ValueError('Motion frame too large')
        return json.loads(raw)
    def close(self):self.ws.close(timeout=.5)


class ProfileHistory:
    def __init__(self,client,store,profile_sink=None,terminal_sink=None,observation_sink=None,status_sink=None,guard_sink=None,history_sink=None):
        self.client = client
        self.store = store
        self.status_sink = status_sink
        self.guard_sink = guard_sink
        self.profile_sink = profile_sink
        self.observation_sink = observation_sink
        self.terminal_sink = terminal_sink
        self.history_sink = history_sink
        self.last_history = None
        self.key = None
        self.error = None
        self.terminal_done = set()
        self.terminal_checked = 0.

    @staticmethod
    def identity(job):return (job['job_id'],job['start_time'],job['filename'])
    @staticmethod
    def mapping(status):
        task=status['print_task_config']
        mapping=validate_mapping(task['extruder_map_table'])
        replenished=validate_mapping(task['extruders_replenished'])
        if replenished!=[0,1,2,3]:raise ValueError('Automatic transition remains blocked')
        return mapping,replenished
    def __call__(self):
        try:
            jobs=self.client.history()
            if self.history_sink:
                from tracker_uid_recovery import TERMINAL
                ended = [j for j in jobs if j.get('status') in TERMINAL]
                signature = [(j.get('job_id'), j.get('start_time'), j.get('filename'),
                              j.get('status')) for j in ended]
                if signature != self.last_history:
                    self.history_sink(ended)
                    self.last_history = signature
            status=self.client.status();stats=status['print_stats']
            if self.status_sink:self.status_sink(status)
            active=[j for j in jobs if j.get('status')=='in_progress' and j.get('filename')==stats.get('filename')]
            if stats.get('state') in ('printing','paused') and not active:
                # History and status are separate HTTP snapshots. A print can
                # start between them. Re-read once and still demand a unique,
                # unchanged identity; this does not forgive a transport gap.
                jobs=self.client.history()
                after=self.client.status()
                if (after['print_stats'].get('state')!=stats.get('state')
                        or after['print_stats'].get('filename')!=stats.get('filename')
                        or after.get('print_task_config')!=status.get('print_task_config')):
                    raise ValueError('Print changed during history/status boundary verification')
                active=[j for j in jobs if j.get('status')=='in_progress' and j.get('filename')==stats.get('filename')]
            if stats.get('state') in ('printing','paused'):
                if len(active)!=1:raise ValueError('Unique active history identity unavailable')
                job=active[0];key=self.identity(job);mapping,replenished=self.mapping(status)
                if type(key[1]) not in (int,float) or not math.isfinite(key[1]) or key[1]<=0:raise ValueError('Invalid history start')
                old=getattr(self.store,'_motion_slicer_profile',None)
                if key!=self.key or old is None:
                    profile=self.client.inspect(job['filename'])
                    after=self.client.status()
                    latest=[j for j in self.client.history() if j.get('status')=='in_progress']
                    if (after['print_stats'].get('filename')!=job['filename'] or after['print_stats'].get('state') not in ('printing','paused')
                            or self.mapping(after)!=(mapping,replenished) or len(latest)!=1 or self.identity(latest[0])!=key):
                        raise ValueError('Print changed during G-code verification')
                    self.store._motion_slicer_profile=dict(profile,history_job_id=job['job_id'],filename=job['filename'],started_at=job['start_time'],mapping=mapping,replenished=replenished,auto_replenish=status['print_task_config'].get('auto_replenish_filament'),feed_start={k:v for k,v in status.items() if k.startswith('filament_feed ')})
                    self.key=key
                elif old.get('auto_replenish')!=status['print_task_config'].get('auto_replenish_filament'):
                    if self.profile_sink:self.profile_sink(job,dict(old,auto_replenish=status['print_task_config'].get('auto_replenish_filament')))
                    raise ValueError('Automatic replacement mode changed during capture')
                elif old['mapping']!=mapping:
                    raise ValueError('Tool mapping changed during capture')
                if self.profile_sink:self.profile_sink(job,self.store._motion_slicer_profile)
                if self.guard_sink:self.guard_sink(job,self.store._motion_slicer_profile)
                if self.observation_sink:self.observation_sink(job,status)
            elif not (self.key and stats.get('filename')==self.key[2] and stats.get('state') in ('complete','cancelled','error')):
                self.store._motion_slicer_profile=None;self.key=None
            if self.terminal_sink and stats.get('state')=='complete':
                latest=sorted(jobs,key=lambda j:j.get('start_time',0),reverse=True)
                if self.observation_sink and latest and latest[0].get('filename')==stats.get('filename') and latest[0].get('status')=='completed':self.observation_sink(latest[0],status)
                if (latest and latest[0].get('status')=='completed' and latest[0].get('filename')==stats.get('filename')
                        and self.identity(latest[0]) not in self.terminal_done and time.monotonic()-self.terminal_checked>=5):
                    self.terminal_checked=time.monotonic()
                    # Refetch the file: a reused filename is not the saved plan.
                    verified=self.client.inspect(latest[0]['filename'])
                    after=self.client.status()
                    if (after.get('print_stats',{}).get('state')=='complete' and after['print_stats'].get('filename')==stats.get('filename') and after.get('print_task_config')==status.get('print_task_config') and all(after.get(k)==v for k,v in status.items() if k.startswith('filament_feed '))):
                        outcome=self.terminal_sink(latest[0],status,verified['file_sha256'])
                        if outcome.get('status') in ('applied','duplicate'):self.terminal_done.add(self.identity(latest[0]))
            self.error=None
            return jobs
        except Exception as exc:
            if not history_read_timeout(exc):
                self.store._motion_slicer_profile=None
                self.key=None
            self.error=str(exc)
            raise


def create_workers(owner,printer,directory):
    u=urlsplit(printer['url']);config={'enabled':True,'host':u.hostname,'port':u.port or (443 if u.scheme=='https' else 80)}
    store=ModelInventoryStore(owner,printer['id'],directory/('motion-'+printer['id']),config)
    client=ReadOnlyMoonraker(printer['url']);history=ProfileHistory(client,store,lambda job,profile:owner.call('recovery_profile',printer['id'],job,profile),lambda job,status,digest:owner.call('recovery_terminal',printer['id'],job,status,digest),lambda job,status:owner.call('replacement_observe',printer['id'],job,status))
    history.history_sink=lambda jobs:owner.call('observe_history',printer['id'],jobs)
    status_client=ReadOnlyMoonraker(printer['url'])
    worker=PrinterWorkers(owner,printer['id'],lambda proxy,pid:MotionStreamRecorder(store,proxy,pid),
                          lambda:MotionSocket(printer['url']),history,config,poll_interval=.5,reconnect_interval=.5,status_reader=status_client.monitor_status)
    def guard_check(job,profile):
        from tracker_uid_guard import execute
        ticket=owner.call('guard_check',printer['id'],job,profile)
        if ticket and ticket['state']=='pause_requested':
            # A persisted pending attempt from an earlier poll is not permission to retry.
            attempt=ticket['attempt']
            if attempt not in attempted:
                attempted.add(attempt);execute(owner,printer['id'],client,ticket)
    attempted=set()
    owner.call('guard_arm',printer['id'])
    # On reconnect/restart, never replay previously issued pause attempts.
    previous=owner.call('guard_snapshot',printer['id'])['guard']
    if previous and previous.get('attempt'):attempted.add(previous['attempt'])
    history.guard_sink=guard_check
    client.stop_event=worker.stop_event
    status_client.stop_event=worker.stop_event
    return worker
