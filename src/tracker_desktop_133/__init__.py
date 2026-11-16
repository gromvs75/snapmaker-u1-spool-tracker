"""Complete published 1.3.3 presentation, without importing its application.

These are presentation sources, not another database/accounting implementation.
Keep the provenance manifest and test every adapter endpoint before changing the
user entrypoint. This module does not instantiate Store or contact a printer.
"""
from pathlib import Path
from . import sender_view,forecast_view,spoolman_view,spoolman_compare_view,settings_view,inventory_view


def published_html():
    html=Path(__file__).with_name('base.html').read_text(encoding='utf-8')
    html=sender_view.install(html)
    html=forecast_view.install(html.replace('1.1.0-beta.1','1.3.3'),lab=False)
    for module in (spoolman_view,spoolman_compare_view,settings_view,inventory_view):
        html=module.install(html)
    return html


def integration_html(token,version):
    """Add the 2.0 bridge while retaining the entire published presentation."""
    import json
    html=published_html()
    html=html.replace("if(!loaded){$('url').value=s.url;","if(!loaded){desktopSpoolmanFormRevision=data.configuration_revision; $('url').value=s.url;")
    html=html.replace("if(!Object.keys(s.outbox).length)$('queue').textContent=t('Операций пока нет','No operations yet');","if(!Object.keys(s.outbox).length)$('queue').textContent=t('Операций пока нет','No operations yet'); window.desktopDeliveryRows?.(data);")
    html=html.replace('Отвязать катушку? Данные Spoolman не удаляются.','Перевести катушку на локальный учёт? UID, назначения и история сохранятся. Незавершённые отправки нужно разрешить заранее.').replace('Detach this spool? Spoolman data is kept.','Switch this spool to local accounting? UID, assignments and history are kept. Resolve unfinished deliveries first.')
    html=html.replace('Списывать филамент в Spoolman после учёта печати','Разрешить явную отправку после проверки каждой операции').replace('Deduct filament in Spoolman after accounting for a print','Allow explicit sending after reviewing each operation')
    html=html.replace("item.remaining_g+t(' г',' g')","displayGrams(item.remaining_g)+t(' г',' g')")
    html=html.replace("const match=words.every(", "const match=(r.dataset.archived==='true')===Boolean(document.getElementById('desktop-archive-view')?.checked)&&words.every(")
    html=html.replace("        const option = node('option', `${spool.name}", "        if(spool.archived)continue;\n        const option = node('option', `${spool.name}")
    html=html.replace("        const choice = node('button', undefined, 'slot-color-option');", "        if(spool.archived)continue;\n        const choice = node('button', undefined, 'slot-color-option');")
    # Only text formatting changes; numeric inputs and the SQLite model stay exact.
    for expression in ('spool.remaining_g','row.required_g','item.required_g','item.remaining_g','grams'):
        html=html.replace('${'+expression+'}', '${displayGrams('+expression+')}')
    html=html.replace('maximumFractionDigits:2','maximumFractionDigits:1')
    html=html.replace("let state = null, selected = null, revision = -1, signature = '';","let state = null, selected = null, revision = -1, signature = ''; let requestSequence=0,appliedSequence=0;")
    html=html.replace('window.refreshSliceForecast = async function(selectLatest = false) {','window.refreshSliceForecast = async function(selectLatest = false) { const request=++requestSequence;')
    html=html.replace('const next = await response.json(); const changed',
                      'const next = await response.json(); if(request<appliedSequence || (desktopFormData && next.printer_id!==desktopFormData.selected_printer)) return; appliedSequence=request; const changed')
    html=html.replace('const changed = next.revision !== revision','const changed = next.slice_revision !== revision')
    html=html.replace('revision = next.revision;','revision = next.slice_revision;')
    html=html.replace('  const entry = entries.find(e => e.source === selected);','  const entry = entries.find(e => e.source === selected);\n  window.desktopForecastSource?.(entry,headData);')
    html=html.replace("entry && entry.shortage ? '#ffab91' : '#82dfb0'","!entry ? '#94a3b8' : entry.shortage ? '#ffab91' : '#82dfb0'")
    html=html.replace("} catch (e) { $('error').textContent = tr().error; }","} catch (e) { if(request<appliedSequence)return; appliedSequence=request; state={entries:[],latest:null,safety_margin_g:state?.safety_margin_g??5}; signature=''; render(); $('error').textContent = tr().error; }")
    html=html.replace('Нет связи с наблюдателем. Показан последний полученный прогноз.','Нет связи с наблюдателем. Актуальность прогноза не подтверждена.')
    html=html.replace('Observer unavailable. Showing the last received forecast.','Observer unavailable. Forecast freshness is unconfirmed.')
    html=html.replace('Beobachter nicht erreichbar. Letzte empfangene Prognose wird angezeigt.','Beobachter nicht erreichbar. Aktualität der Prognose ist unbestätigt.')
    html=html.replace('Нет актуального остатка Spoolman','Назначение или остаток не подтверждены').replace('Spoolman balance unavailable','Assignment or balance is unconfirmed')
    html=html.replace('${Math.round(grams * 1000) / 1000}','${displayGrams(grams)}')
    html=html.replace('    renderPreflight(data, true);','    window.desktopInventoryLoaded?.(data);\n    renderPreflight(data, true);')
    # This sentence is true for 1.3.3, but not for the optional RFID module in 2.0.
    for old,new in [
        ('Spool tracking and usage forecasts for Snapmaker U1 — without firmware changes.','Spool tracking and usage forecasts for Snapmaker U1. RFID requires the printer module.'),
        ('Учёт катушек и прогноз расхода для Snapmaker U1 — без изменения прошивки.','Учёт катушек и прогноз расхода для Snapmaker U1. Для RFID нужен модуль принтера.'),
        ('Spulenverwaltung und Verbrauchsprognosen für Snapmaker U1 — ohne Firmware-Änderungen.','Spulenverwaltung für Snapmaker U1. RFID benötigt das Druckermodul.'),
        ('Облік котушок і прогноз витрат для Snapmaker U1 — без зміни прошивки.','Облік котушок для Snapmaker U1. Для RFID потрібен модуль принтера.'),
        ('Gestión de bobinas y previsión de consumo para Snapmaker U1 — sin modificar el firmware.','Gestión de bobinas para Snapmaker U1. RFID requiere el módulo de impresora.')]:
        html=html.replace(old,new)
    bootstrap=Path(__file__).with_name('bridge.js').read_text(encoding='utf-8')
    bootstrap=bootstrap.replace('__TOKEN__',json.dumps(token)).replace('__VERSION__',json.dumps(version))
    html=html.replace('<script>','<script>'+bootstrap+'</script><script>',1)
    extension='\n'.join(Path(__file__).with_name(name+'.js').read_text(encoding='utf-8') for name in ('inventory','printers','connections','tags','delivery','forecast','history','maintenance'))
    html=html.replace('</body>','<script>'+extension+'</script></body>')
    return html.replace('· 1.3.3','· '+version)
