"""Fault injection at the research receiver of real Klipper/Moonraker RPCs."""
from .barrier_protocol import Receiver


def exercise(printer, wait):
    checks=[];trace=[]
    def check(name, ok):
        assert ok, name
        checks.append(name)
        print('PASS barrier: '+name, flush=True)
    def rpc(action, **args):
        r=printer.http('/printer/bench_motion/event',dict(action='barrier_'+action,**args))['result']
        trace.append(dict(action=action,response=r))
        return r
    def value(action, **args):return rpc(action,**args)['value']
    epoch=value('start')['epoch'];r=Receiver(epoch)
    a=value('packet',head=3,start=1,end=2,length=100);r.packet(a)
    value('packet',head=3,start=2,end=3,length=2,delayed=1)
    check('source refuses seal before pending motion emitted','rejected' in rpc('seal',id='pause',fence=10))
    late=value('flush')['packets'][0]
    c=value('packet',head=1,start=3,end=4,length=5);r.packet(c)
    b=value('seal',id='pause',fence=10)
    check('lost barrier is not silently inferred',not r.result('pause')['boundary_proven'])
    r.barrier(b)
    check('missing sequence blocks boundary despite source seal',not r.result('pause')['boundary_proven'])
    r.packet(a);r.barrier(value('seal',id='pause',fence=10))
    check('exact replays cannot fill sequence gap',not r.result('pause')['boundary_proven'])
    r.packet(late)
    check('late missing packet completes same-session prefix',r.result('pause')['boundary_proven'] and not r.result('pause')['authorizes_debit'])
    r.packet(late);r.barrier(b)
    check('exact repeated packets and barrier are idempotent',len(r.packets)==3 and len(r.barriers)==1)
    check('source rejects later movement before sealed fence','rejected' in rpc('packet',head=1,start=9,end=10,length=1))
    check('source rejects changed retry','rejected' in rpc('seal',id='pause',fence=11))
    d=value('packet',head=1,start=11,end=12,length=20);r.packet(d)
    resume=value('seal',id='resume',fence=20);r.barrier(resume)
    check('second ordered boundary completes without debit permission',r.result('resume')['boundary_proven'] and not r.result('resume')['authorizes_debit'])
    bad=Receiver(epoch);bad.packet(a)
    try:bad.packet(dict(a,length=101))
    except ValueError:pass
    bad_result=bad.result('pause')
    check('conflicting replay poisons capture',bool(bad.failure) and not bad_result['boundary_proven'])
    r.disconnect();printer.stop_m();printer.start_m()
    wait(lambda:printer.http('/printer/objects/query?bench_transition'))
    replay=value('seal',id='resume',fence=20)
    check('source epoch survives Moonraker restart',replay==resume)
    try:r.barrier(replay)
    except ValueError:pass
    check('reconnect cannot restore old proof',not r.result('pause')['boundary_proven'] and not r.result('resume')['boundary_proven'])
    new_epoch=value('start')['epoch'];fresh=Receiver(new_epoch)
    try:fresh.barrier(b)
    except ValueError:pass
    check('old epoch replay rejected after fresh source capture',new_epoch!=epoch and bool(fresh.failure))
    # Fresh explicitly-started capture can prove its own prefix, not the old job.
    fresh=Receiver(new_epoch);q=value('packet',head=1,start=21,end=22,length=1);fresh.packet(q)
    final=value('seal',id='fresh',fence=30);fresh.barrier(final)
    check('fresh capture never repairs previous epoch or authorizes debit',fresh.result('fresh')['boundary_proven'] and not fresh.result('fresh')['authorizes_debit'] and not r.result('resume')['boundary_proven'])
    return dict(checks=checks,trace=trace,old_capture=r.result('resume'),fresh_capture=fresh.result('fresh'),fault_injection='Receiver deliberately omits/repeats RPC packet objects; not an OS packet-loss test')
