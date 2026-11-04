import math
import pytest
from motion_analysis import HeadMotionSummary, MotionDataError


def segment(time, direction=1, duration=1, speed=10, accel=0):
    return [time, duration, speed, accel, [0, 0, 0], [direction, 0, 0]]


def test_separates_heads_and_subtracts_retraction():
    summary = HeadMotionSummary()
    summary.add(0, [segment(1), segment(2, -1, .2)])
    summary.add(2, [segment(1, 1, .5, 4, 2)])
    result = summary.result()
    assert result[0]['net_mm'] == 8
    assert result[0]['retraction_mm'] == 2
    assert result[2]['net_mm'] == 2.25
    assert result[1]['segments'] == 0


@pytest.mark.parametrize('bad', [[], [1, 2], segment(1, speed=float('nan')), segment(1, duration=-1)])
def test_invalid_samples_invalidate_the_whole_summary(bad):
    summary = HeadMotionSummary()
    with pytest.raises(MotionDataError): summary.add(0, [bad])
    with pytest.raises(MotionDataError): summary.result()


def test_replayed_or_overlapping_segments_invalidate_summary():
    summary = HeadMotionSummary()
    summary.add(0, [segment(1)])
    with pytest.raises(MotionDataError, match='Overlapping'):
        summary.add(0, [segment(1)])
    with pytest.raises(MotionDataError): summary.result()


def test_signed_velocity_and_acceleration_record_retraction():
    summary = HeadMotionSummary()
    summary.add(0, [segment(1, speed=0, accel=-4)])
    assert summary.result()[0]['net_mm'] == -2


def test_tiny_negative_duration_from_floating_point_is_zero():
    summary = HeadMotionSummary()
    summary.add(0, [segment(1, duration=-5e-18)])
    assert summary.result()[0]['net_mm'] == 0


def test_printer_aggregate_comparison_detects_missing_motion():
    summary = HeadMotionSummary()
    summary.add(0, [segment(1, speed=10)])
    summary.add(1, [segment(1, speed=5)])
    assert summary.compare_printer_total(15)['matches'] is True
    assert summary.compare_printer_total(20)['matches'] is False
    with pytest.raises(MotionDataError): summary.compare_printer_total(None)
    with pytest.raises(MotionDataError): summary.compare_printer_total(float('nan'))
    with pytest.raises(MotionDataError): summary.compare_printer_total(0)
