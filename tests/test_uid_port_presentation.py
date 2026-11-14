from tracker_uid_presentation import history_presentation

def test_accounted_hides_obsolete_review_but_resolved_keeps_uncertainty():
    job=dict(job_key='a',state='completed',mapping_valid=1,last_sequence=1)
    debits=[dict(job_key='a',delta_mg=1234)]
    assert history_presentation(job,debits,[{'reason':'old'}])==dict(label='Учтено',reason='',accounted_mg=1234)
    job['state']='resolved'
    assert history_presentation(job,debits,[])['reason']

def test_active_identity_not_filename_and_disconnect_does_not_claim_sleep():
    a=dict(job_key='a',state='active',mapping_valid=1,last_sequence=-1,filename='same.gcode')
    b=dict(a,job_key='b',mapping_valid=0)
    assert history_presentation(a,[],[])['label']=='Печатается — ожидаем завершения'
    status=history_presentation(b,[],[])
    assert 'уточнения' in status['label'] and 'сон' not in status['reason']


def test_terminal_history_waits_for_usage_review_not_completion():
    job=dict(job_key='a',state='active',mapping_valid=0,last_sequence=-1,history_status='completed')
    p=history_presentation(job,[],[])
    assert p['label']=='Печать завершена — требуется сверка расхода'
    assert p['accounted_mg']==0


def test_reviewed_estimate_explains_source():
    import json
    job=dict(job_key='a',state='completed',mapping_valid=0,last_sequence=1)
    p=history_presentation(job,[dict(job_key='a',delta_mg=2983)],[],[dict(job_key='a',payload=json.dumps(dict(estimate_source='manual_reconciliation',note='Проверено')))])
    assert p['label']=='Учтено расчётно'
    assert 'подтверждён вручную' in p['reason'] and p['accounted_mg']==2983
