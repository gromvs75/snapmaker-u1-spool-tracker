from tag_evidence import TagEvidence


def status(uids):
    return {'filament_detect': {'state': [0]*4, 'info': [{'CARD_UID': u} for u in uids]}}


def test_two_untagged_spools_are_not_conflated():
    e = TagEvidence(); e.apply(status([0, 0, [1,2,3,4], 0])); e = e.for_new_job()
    out = e.report({'runouts':[False]*4})
    assert out['known'] and out['unchanged'] == [True]*4
    assert out['initial'][:2] == [None, None]


def test_changed_uid_and_missing_scanner_are_not_stable():
    e = TagEvidence(); e.apply(status([[1,2,3,4], 0, 0, 0])); e = e.for_new_job()
    e.apply(status([[4,3,2,1], 0, 0, 0]))
    assert not e.report({'runouts':[False]*4})['unchanged'][0]
    e.apply({'filament_detect': {'state':[1,0,0,0]}})
    assert not e.report({'runouts':[False]*4})['known']
