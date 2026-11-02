from print_statistics import summarize_prints


def test_statistics_exclude_incomplete_and_keep_manual_allocations_separate():
    data = {"runs": {
        "a": {"status": "committed", "start_time": 1793119239, "physical_weights": [1, 2, 0, 0]},
        "b": {"status": "committed", "start_time": 1793119239, "accounting_method": "manual_review",
              "physical_weights": [9, 0, 0, 0], "manual_consumption": {"spool_a": 4, "spool_b": 6}},
        "c": {"status": "review", "start_time": 1793119239, "physical_weights": [20, 0, 0, 0]},
        "d": {"status": "cancelled", "start_time": 1793119239},
    }}
    result = summarize_prints(data)
    assert result["counts"] == {"active": 0, "committed": 2, "cancelled": 1, "error": 0, "review": 1}
    assert result["head_estimated_g"] == [1, 2, 0, 0]
    assert result["manual_spool_g"] == {"spool_a": 4, "spool_b": 6}
    assert result["by_month"]["2026-10"] == {"committed": 2, "estimated_g": 3, "manual_g": 10, "motion_g": 0}


def test_scale_readings_preserve_estimate_and_replacement_uncertainty():
    data = {'runs': {'a': {'status':'committed', 'start_time':1793119239, 'filename':'a.gcode',
             'accounting_method':'manual_review', 'physical_spool_ids':['s', '', '', ''],
             'physical_weights':[12, 0, 0, 0], 'manual_consumption':{'s':10},
             'manual_measurements':{'s':{'before_g':500, 'after_g':490}},
             'review_reason':'Automatic replenishment cannot be ruled out'}}}
    row = summarize_prints(data)['weighed_records'][0]
    assert row['weighed_g'] == 10
    assert row['initial_gcode_estimate_g'] == 12
    assert row['estimate_may_be_affected_by_replacement'] is True
