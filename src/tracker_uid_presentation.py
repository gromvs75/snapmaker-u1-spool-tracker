"""Read-only history labels; never feed display state back into accounting."""

import json

SOURCES = {
    'printer_history_estimate':'Расчёт по счётчику истории принтера',
    'completed_slicer_estimate':'Расчёт по полному плану слайсера',
    'slicer_and_exhausted_remainder':'План слайсера и остаток Tracker при автозамене',
    'history_counter_and_paused_uid_segments':'Счётчик истории и замены UID на паузе',
    'slicer_plan_and_paused_uid_segments':'План слайсера и замены UID на паузе',
    'manual_reconciliation':'Расчёт подтверждён вручную',
    'layer_range_estimate':'Диапазон расхода по указанному слою',
}


def history_presentation(job, debits, reviews, receipts=()):
    amount=sum(d['delta_mg'] for d in debits if d['job_key']==job['job_key'])
    receipt=next((json.loads(r['payload']) for r in receipts if r['job_key']==job['job_key']),None)
    if receipt:
        return {'label':'Учтено расчётно' if job['state']=='completed' else 'Прервано — учтено расчётно',
                'reason':'Оценка расхода, не взвешивание. '+SOURCES.get(receipt.get('estimate_source'),'Расчёт по истории'),
                'accounted_mg':amount,'receipt':receipt}
    if job['state']=='resolved':
        return {'label':'Закрыто вручную — без дополнительного списания','reason':'Недоказанный расход остался неучтённым.','accounted_mg':amount}
    if job['state'] in ('completed','cancelled') and job['last_sequence']>=0:
        return {'label':'Учтено' if job['state']=='completed' else 'Отменено — учтён фактический расход','reason':'','accounted_mg':amount}
    if job['state']=='active' and job.get('history_status') in ('completed','cancelled','error','interrupted','klippy_shutdown','klippy_disconnect'):
        return {'label':('Печать завершена' if job['history_status']=='completed' else 'Печать прервана')+' — требуется сверка расхода',
                'reason':'История получена. Проверьте распределение между катушками.','accounted_mg':amount}
    if job['state']=='active' and job['mapping_valid']:
        return {'label':'Печатается — ожидаем завершения','reason':'','accounted_mg':amount}
    reason='Непрерывность наблюдения не подтверждена. Требуется проверка.'
    return {'label':'Ожидаем уточнения состояния печати','reason':reason,'accounted_mg':amount}
