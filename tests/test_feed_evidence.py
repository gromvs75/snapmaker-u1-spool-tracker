from feed_evidence import FeedEvidence


def channel(present=True):
    return {'module_exist': True, 'disable_auto': False, 'filament_detected': present}


def initial():
    return {'filament_feed left': {'extruder0': channel(), 'extruder1': channel()},
            'filament_feed right': {'extruder2': channel(), 'extruder3': channel()}}


def test_runout_and_insertion_are_not_confused():
    e = FeedEvidence(); e.apply(initial())
    e.apply({'filament_feed left': {'extruder0': {'filament_detected': False}}})
    assert e.report()['runouts'] == [True, False, False, False]
    assert e.report()['insertions'] == [False] * 4
    e.apply({'filament_feed left': {'extruder0': {'filament_detected': True}}})
    assert e.report()['insertions'] == [True, False, False, False]
    assert e.report()['proves_spool_identity'] is False


def test_missing_disabled_and_malformed_feeders_fail_closed():
    e = FeedEvidence(); e.apply({'filament_feed left': {'extruder0': channel()}})
    assert e.report()['covered'] == [True, False, False, False]
    e.apply({'filament_feed left': {'extruder0': {'disable_auto': True}}})
    assert e.report()['covered'][0] is False
    e.apply({'filament_feed right': {'extruder2': {'filament_detected': 1}}})
    assert e.report()['valid'] is False
