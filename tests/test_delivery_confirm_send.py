import pytest
from concurrent.futures import ThreadPoolExecutor
from test_uid_delivery import bench


def request(o):
    o.call('save_settings',dict(spoolman_mode='send'),o.call('settings')['revision'])
    row=o.call('delivery_list')[0]
    return dict(operation_id=row['operation_id'],expected_revision=row['revision'],request_id='direct-send-1',confirmed=True)


def test_one_confirm_sends_once_under_concurrent_retries(bench):
    o,f,s,*_=bench;q=request(o)
    with ThreadPoolExecutor(2) as p:results=list(p.map(lambda _:s.confirm_send(**q),range(2)))
    assert results==[{'status':'sent'}]*2 and len(f.writes)==1
    assert [r['state'] for r in o.call('delivery_audit')]==['pending','sending','sent']


@pytest.mark.parametrize('fault',['drop_before','drop_after','http_error','bad_reply'])
def test_direct_unknown_write_never_retries(bench,fault):
    o,f,s,*_=bench;q=request(o);f.fault=fault
    assert s.confirm_send(**q)['status']=='uncertain';f.fault=''
    for _ in range(3):assert s.confirm_send(**q)['status']=='uncertain'
    assert len(f.writes)==1 and len(o.call('inspect')['debits'])==1


def test_offline_preflight_retry_keeps_approval_receipt(bench):
    o,f,s,*_=bench;q=request(o);f.fault='offline'
    assert s.confirm_send(**q)['status']=='unavailable' and not f.writes
    f.fault='';assert s.confirm_send(**q)['status']=='sent' and len(f.writes)==1


@pytest.mark.parametrize('fault',['read_only','stale','unconfirmed','not_allowed'])
def test_direct_send_guards(bench,fault):
    o,f,s,*_=bench;q=request(o)
    if fault=='read_only':
        o.call('save_settings',dict(spoolman_mode='read'),o.call('settings')['revision'])
        assert s.confirm_send(**q)['status']=='disabled'
    else:
        if fault=='stale':q['expected_revision']='stale'
        if fault=='unconfirmed':q['confirmed']=False
        if fault=='not_allowed':s._allowed_urls=()
        with pytest.raises(ValueError):s.confirm_send(**q)
    assert not f.writes and o.call('delivery_list')[0]['state']=='held'
