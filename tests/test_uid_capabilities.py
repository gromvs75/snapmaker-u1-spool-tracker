import copy
import json
import pytest
from tracker_uid_client import UidClient, PrinterEndpoint
from tracker_printer_capabilities import manual_available, manual_edit_available
from test_uid_client import status


def session(values, *, module=True):
    client=UidClient(PrinterEndpoint('a','A','http://localhost:1'),poll_interval=.001)
    class Socket:
        calls=[]
        pending=None
        def send(self,raw):
            req=json.loads(raw);self.calls.append(req)
            if req['method']=='printer.objects.list':
                result={'objects':['print_stats','webhooks']+(['tracker_uid'] if module else [])}
            else:
                value=values.pop(0)
                result={'status':dict(print_stats={'state':'standby'},webhooks={'state':'ready'})}
                if module:result['status']['tracker_uid']=value
                if not values:client._stop.set()
            self.pending=json.dumps({'id':req['id'],'result':result})
        def recv(self):
            if self.pending:
                result=self.pending;self.pending=None;return result
            raise TimeoutError()
    # rpc must read the last response before it sees the stop flag.
    class StopAfterReply(Socket):
        def send(self,raw):
            super().send(raw);self.last=client._stop.is_set();client._stop.clear()
        def recv(self):
            result=super().recv()
            if self.last:client._stop.set()
            return result
    ws=StopAfterReply();client._session(ws)
    return client,ws.calls


def test_missing_module_is_connected_stock_printer_not_uid_ready():
    c,calls=session([None],module=False)
    s=c.snapshot()
    assert s['state']=='module_missing' and s['printer_connected']
    assert manual_edit_available(s)
    assert all(ch['uid'] is None for ch in s['channels'].values())
    assert calls[-1]['params']['objects']=={'print_stats':None,'webhooks':None}


def test_valid_module_keeps_uid_and_independent_printer_status():
    c,_=session([status()])
    assert c.snapshot()['state']=='ready'
    assert c.snapshot()['channels']['0']['uid']=='04112233'
    assert manual_available(c.snapshot())


@pytest.mark.parametrize('bad',[None,{},dict(schema_version=2),dict(schema_version=True)])
def test_invalid_module_is_distinct_and_cannot_authorize_manual_or_uid(bad):
    c,_=session([bad])
    assert c.snapshot()['printer_connected']
    assert c.snapshot()['state']=='invalid_data'
    assert not manual_available(c.snapshot())
    assert all(ch['uid'] is None for ch in c.snapshot()['channels'].values())


def test_reordered_packet_fences_assignments_even_if_next_poll_recovers():
    c,_=session([status(seq=9),status(seq=8),status(seq=10)])
    assert c.snapshot()['state']=='ready' and c.snapshot()['generation']==1


def test_sleep_gap_fences_connection_even_without_socket_close():
    c,_=session([None],module=False)
    c._printer_received-=20
    c._accept_printer({'webhooks':{'state':'ready'},'print_stats':{'state':'printing'}})
    assert c.snapshot()['generation']==1
    assert manual_available(c.snapshot()) and not manual_edit_available(c.snapshot())
