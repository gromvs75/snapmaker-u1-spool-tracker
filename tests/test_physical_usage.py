import pytest

from physical_usage import MotionLedger, UsageEvidenceError


def finish(ledger, count):
    return ledger.finish(count, completed=True, continuous=True, confirmed_spools=True)


def test_split_motion_between_original_and_replacement_spools():
    ledger = MotionLedger('job')
    ledger.record(0, 0, 'first', 100, 1, .003)
    ledger.record(1, 0, 'first', -2, 1, .003)
    ledger.record(2, 1, 'replacement', 50, 1, .003)
    assert finish(ledger, 3) == {'first': .294, 'replacement': .15}


def test_flow_factor_is_not_applied_twice_to_physical_motion():
    ledger = MotionLedger('job')
    ledger.record(0, 0, 'one', 100, 1, .003)
    ledger.record(1, 0, 'one', 200, 2, .003)
    assert finish(ledger, 2) == {'one': .9}


@pytest.mark.parametrize('sequence, head, spool, delta, factor, conversion', [
    (1, 0, 'a', 1, 1, .003), (0, 4, 'a', 1, 1, .003),
    (0, 0, '', 1, 1, .003), (0, 0, 'a', float('nan'), 1, .003),
    (0, 0, 'a', 1, 0, .003), (0, 0, 'a', 1, 1, 0),
])
def test_invalid_or_incomplete_evidence_cannot_be_committed(sequence, head, spool, delta, factor, conversion):
    ledger = MotionLedger('job')
    with pytest.raises(UsageEvidenceError):
        ledger.record(sequence, head, spool, delta, factor, conversion)
    with pytest.raises(UsageEvidenceError):
        finish(ledger, 0)


@pytest.mark.parametrize('completed,continuous,confirmed', [(False, True, True), (True, False, True), (True, True, False)])
def test_uncertain_finished_job_cannot_be_committed(completed, continuous, confirmed):
    ledger = MotionLedger('job')
    ledger.record(0, 0, 'a', 1, 1, .003)
    with pytest.raises(UsageEvidenceError):
        ledger.finish(1, completed=completed, continuous=continuous, confirmed_spools=confirmed)


def test_missing_final_motion_is_detected():
    ledger = MotionLedger('job')
    ledger.record(0, 0, 'a', 1, 1, .003)
    with pytest.raises(UsageEvidenceError, match='incomplete'):
        finish(ledger, 2)
