"""Read-only history labels; never feed display state back into accounting."""

def history_presentation(job, debits, reviews):
    amount=sum(d['delta_mg'] for d in debits if d['job_key']==job['job_key'])
    if job['state']=='resolved':
        return {'label':'Закрыто вручную — без дополнительного списания','reason':'Недоказанный расход остался неучтённым.','accounted_mg':amount}
    if job['state'] in ('completed','cancelled') and job['last_sequence']>=0:
        return {'label':'Учтено' if job['state']=='completed' else 'Отменено — учтён фактический расход','reason':'','accounted_mg':amount}
    if job['state']=='active' and job['mapping_valid']:
        return {'label':'Печатается — ожидаем завершения','reason':'','accounted_mg':amount}
    reason='Непрерывность наблюдения не подтверждена. Требуется проверка.'
    return {'label':'Ожидаем уточнения состояния печати','reason':reason,'accounted_mg':amount}
