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
    # Only text formatting changes; numeric inputs and the SQLite model stay exact.
    for expression in ('spool.remaining_g','row.required_g','item.required_g','item.remaining_g','grams'):
        html=html.replace('${'+expression+'}', '${displayGrams('+expression+')}')
    html=html.replace('maximumFractionDigits:2','maximumFractionDigits:1')
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
    extension=Path(__file__).with_name('inventory.js').read_text(encoding='utf-8')+'\n'+Path(__file__).with_name('history.js').read_text(encoding='utf-8')
    html=html.replace('</body>','<script>'+extension+'</script></body>')
    return html.replace('· 1.3.3','· '+version)
