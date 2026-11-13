"""Research-only boundary consistency checks. Never authorizes a debit.

Checkpoint counters must share a proven event-time fence, not arrival time.
Synthetic ground truth is useful for tests and is not available in U1 logs.
No constant offset, fitted final correction or relaxed production tolerance.
"""
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class Checkpoint:
    heads: tuple
    printer: float
    clock: str
    fence: float
    settled: bool
    identity: tuple
    epoch: str


def delta(left, right):
    if (len(left.heads)!=4 or len(right.heads)!=4 or not left.clock or left.clock!=right.clock
            or not left.settled or not right.settled or right.fence<=left.fence
            or not left.epoch or left.epoch!=right.epoch or left.identity!=right.identity
            or len(left.identity)!=4 or not all(left.identity)):
        raise ValueError('Unproven fence, identity, or continuity')
    values=(*left.heads,*right.heads,left.printer,right.printer,left.fence,right.fence)
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in values):
        raise ValueError('Invalid counters')
    heads=tuple(b-a for a,b in zip(left.heads,right.heads))
    printer=right.printer-left.printer
    if printer<0:raise ValueError('Printer counter reset')
    return heads,printer


def printing_interval(left, right):
    heads,printer=delta(left,right)
    difference=math.fsum(heads)-printer
    return {'kind':'printing','consistent':abs(difference)<=.1,'difference_mm':difference,
            'physical_heads_delta_mm':heads,'authorizes_debit':False}


def automatic_boundary(left, right, *, source_head, target_head, runout, mapping,
                       service_heads=None, service_counter=None, provenance=None):
    """Service movement must come from independent aligned command evidence.

    Do not construct service_heads/counter by subtracting endpoint totals. This
    protocol is a hypothesis for future firmware evidence, not a collector API.
    """
    heads,printer=delta(left,right)
    if (type(source_head) is not int or type(target_head) is not int
            or source_head not in range(4) or target_head not in range(4)
            or source_head==target_head or runout is not True or len(mapping)!=4
            or mapping[source_head]!=target_head):
        raise ValueError('Automatic transition not established')
    if provenance not in ('aligned_firmware_commands','synthetic_ground_truth') or service_heads is None or service_counter is None:
        return {'kind':'automatic_boundary','consistent':False,'reason':'Independent service movement evidence missing',
                'observed_scope_difference_mm':math.fsum(heads)-printer,'authorizes_debit':False}
    if len(service_heads)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in (*service_heads,service_counter)):
        raise ValueError('Invalid service evidence')
    residuals=tuple(a-b for a,b in zip(heads,service_heads))
    residual_counter=printer-service_counter
    # Check each physical head separately, not just a cancellation of errors.
    return {'kind':'automatic_boundary','consistent':all(abs(v)<=.1 for v in residuals) and abs(residual_counter)<=.1,
            'head_residuals_mm':residuals,'counter_residual_mm':residual_counter,
            'physical_service_heads_mm':service_heads,'authorizes_debit':False}


def reported_drift():
    resume=6191.473010012691-6179.313040012552
    final=11728.790089980172-11716.630119980022
    return {'resume_offset_mm':resume,'final_offset_mm':final,'offset_change_mm':final-resume,
            'post_resume_motion_delta_mm':11728.790089980172-6191.473010012691,
            'post_resume_counter_delta_mm':11716.630119980022-6179.313040012552,
            'source':'reported aggregates; not a replay of private raw logs',
            'authorizes_debit':False,'boundary_proven':False}


def partition_motion(packets, *, pause_fence, resume_fence, clock, epoch):
    """Research only: classify whole event-time intervals, never arrival state.

    A packet crossing a fence cannot be apportioned by duration without a
    proven velocity profile. Even a complete partition does not explain which
    service commands entered the printer's filament counter.
    """
    if not clock or not epoch or not math.isfinite(pause_fence) or not math.isfinite(resume_fence) or pause_fence>=resume_fence:
        raise ValueError('Unproven boundary clock')
    groups={k:[] for k in ('before','service','after','ambiguous')};seen={};intervals={}
    for p in packets:
        if p.get('clock')!=clock or p.get('epoch')!=epoch:raise ValueError('Clock or epoch mismatch')
        head=p.get('head');start=p.get('start');end=p.get('end');length=p.get('length');key=p.get('id')
        if type(head) is not int or head not in range(4) or not isinstance(key,str) or not key or any(type(v) not in (int,float) or not math.isfinite(v) for v in (start,end,length)) or end<=start:
            raise ValueError('Invalid interval')
        canonical=(head,start,end,length)
        if key in seen:
            if seen[key]!=canonical:raise ValueError('Conflicting replay')
            continue
        if any(start<b and end>a for a,b in intervals.get(head,[])):raise ValueError('Overlapping packets')
        seen[key]=canonical;intervals.setdefault(head,[]).append((start,end))
        phase='before' if end<=pause_fence else 'after' if start>=resume_fence else 'service' if start>=pause_fence and end<=resume_fence else 'ambiguous'
        groups[phase].append(dict(p))
    return dict(groups=groups,fully_partitioned=not groups['ambiguous'],authorizes_debit=False,
                reason='Counter inclusion of service commands remains unproven')
