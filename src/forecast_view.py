"""Overview extension, installed only by the isolated forecast lab."""
MARKUP = """
<style>#nav-sender,.overview-card {display:none!important} #slice-forecast{border-color:#35506b} #slice-forecast h2{font-size:22px}
#slice-forecast {padding:18px 22px;margin-bottom:18px}
#slice-forecast h2 {font-size:16px;margin:0}
#slice-forecast .overview-heading {align-items:center;gap:12px}
#slice-forecast .overview-status {font-size:22px;margin:12px 0 6px}
#slice-forecast #forecast-hide {width:auto;flex:0 0 auto;padding:6px 10px;font-size:13px;background:transparent;border:1px solid #42516a;color:#b5c3d8}
#slice-forecast #forecast-plate {width:auto;min-width:140px;max-width:220px;flex:0 0 auto;padding:5px 10px;font-size:14px}
#slice-forecast [hidden] {display:none!important}
#forecast-error:empty {display:none}
#slice-forecast .forecast-footnote {font-size:12px;color:#94a3b8;margin:6px 0 0}
#slice-forecast .forecast-mapping {color:#d6b879}
#forecast-time {font-size:13px}
.forecast-meta {display:flex;align-items:center;flex-wrap:wrap;gap:8px 16px;color:#94a3b8;font-size:14px}
#forecast-project,#forecast-time {margin:0}
.forecast-head-status {font-size:17px;font-weight:700;margin-top:10px}
.forecast-head-status.ok {color:#82dfb0}
.forecast-head-status.shortage {color:#ff8f8f}
.forecast-head-status.unused {color:#94a3b8;font-weight:400}
.forecast-head-note {font-size:13px;color:#94a3b8;margin-top:4px}
#sidebar-slots .printhead-visual {position:relative}
.forecast-head-icon {position:absolute;right:-16px;top:-8px;border-radius:50%;width:32px;height:32px;display:grid;place-items:center;background:#101722;font-weight:800;font-size:24px;border:2px solid currentColor}
.forecast-head-icon.ok {color:#82dfb0}
.forecast-head-icon.shortage {color:#ff8f8f}
</style>
<section class="card" id="slice-forecast" aria-labelledby="forecast-heading">
 <div class="overview-heading"><h2 id="forecast-heading">Прогноз после нарезки</h2>
 <button id="forecast-hide" type="button" title="Скрыть в строку меню, продолжая наблюдение">Скрыть в меню</button></div>
 <p id="forecast-status" class="overview-status" aria-live="polite">Ожидаем нарезку</p>
 <div class="forecast-meta">
 <span id="forecast-single"></span><select id="forecast-plate" aria-label="Пластина" hidden></select>
 <p id="forecast-time"></p></div>
 <p class="forecast-footnote"><span id="forecast-reserve"></span> · <span id="forecast-no-debit">Без списания</span></p>
 <p class="forecast-footnote forecast-mapping">Материалы: 1→T0 · 2→T1 · 3→T2 · 4→T3 (предположение)</p>
 <p id="forecast-error" role="status"></p>
</section>
"""
SCRIPT = r"""
<script>
(() => {
 let state = null, selected = null, revision = -1, signature = '';
 const $ = id => document.getElementById('forecast-' + id);
 const texts = {
 ru: {title:'Прогноз после нарезки',hide:'Скрыть в меню',enough:'Материала хватает',shortage:'Материала не хватает',waiting:'Ожидаем нарезку Snorca',reserve:'Резерв',per:'на используемую катушку',noDebit:'Без списания',mapping:'Материалы: 1→T0 · 2→T1 · 3→T2 · 4→T3 (предположение)',plate:'Пластина',after:'После печати ≈ ',missing:'Не хватает ',withReserve:' с учётом резерва',unused:'Не используется',ok:'Хватит',bad:'Не хватит',usage:'Плановый расход после нарезки',error:'Нет связи с наблюдателем. Показан последний полученный прогноз.'},
 en: {title:'Slice forecast',hide:'Hide to tray',enough:'Enough filament',shortage:'Not enough filament',waiting:'Waiting for a Snorca slice',reserve:'Reserve',per:'per used spool',noDebit:'No inventory deduction',mapping:'Materials: 1→T0 · 2→T1 · 3→T2 · 4→T3 (assumed)',plate:'Plate',after:'After printing ≈ ',missing:'Short by ',withReserve:' including reserve',unused:'Not used',ok:'Enough',bad:'Insufficient',usage:'Estimated usage after slicing',error:'Observer unavailable. Showing the last received forecast.'},
 de: {title:'Prognose nach dem Slicen',hide:'In Menüleiste ausblenden',enough:'Filament reicht aus',shortage:'Filament reicht nicht aus',waiting:'Warte auf Snorca-Slicing',reserve:'Reserve',per:'pro verwendeter Spule',noDebit:'Kein Verbrauch gebucht',mapping:'Materialien: 1→T0 · 2→T1 · 3→T2 · 4→T3 (angenommen)',plate:'Platte',after:'Nach dem Druck ≈ ',missing:'Es fehlen ',withReserve:' einschließlich Reserve',unused:'Nicht verwendet',ok:'Ausreichend',bad:'Nicht ausreichend',usage:'Geschätzter Verbrauch nach dem Slicen',error:'Beobachter nicht erreichbar. Letzte empfangene Prognose wird angezeigt.'}
 };
 const tr = () => texts[currentLang] || texts.en;
 const grams = value => Number(value).toLocaleString(currentLang || 'en', {maximumFractionDigits:2}) + (currentLang === 'ru' ? ' г' : ' g');
 function paintHeads() {
  const entry = state && state.entries.find(e => e.source === selected);
  document.querySelectorAll('#sidebar-slots .sidebar-slot').forEach((head, i) => {
   head.querySelectorAll('.forecast-head-status,.forecast-head-note,.forecast-head-icon').forEach(e => e.remove());
   const row = entry && entry.rows[i];
   if (!row) return;
   head.querySelectorAll('.head-state,.head-required').forEach(e => e.remove());
   const kind = row.used === 0 ? 'unused' : row.enough ? 'ok' : 'shortage';
   const symbol = row.enough ? '✓' : '✕';
   const status = document.createElement('div'); status.className = 'forecast-head-status ' + kind;
   status.textContent = row.used === 0 ? tr().unused : symbol + ' ' + (row.enough ? tr().ok : tr().bad);
   head.append(status);
   const caption = head.querySelector('.printhead-material');
   if (caption) {caption.textContent = grams(row.used); caption.title = tr().usage;}
   const note = document.createElement('div'); note.className = 'forecast-head-note';
   if (row.used > 0) {
    note.textContent = row.enough ? tr().after + grams(row.after) : tr().missing + grams(Math.max(0, state.safety_margin_g - row.after)) + tr().withReserve;
    head.append(note);
   }
   if (row.used > 0) {
    const icon = document.createElement('span'); icon.className = 'forecast-head-icon ' + kind;
    icon.textContent = symbol; icon.setAttribute('aria-hidden','true');
    const visual = head.querySelector('.printhead-visual'); if (visual) visual.append(icon);
   }
  });
 }
 const baseRenderSidebar = renderSidebar;
 renderSidebar = function(data) {baseRenderSidebar(data); paintHeads();};
 function render() {
  const entries = state.entries;
  $('heading').textContent = tr().title;
  $('hide').textContent = tr().hide; $('hide').title = tr().hide;
  document.querySelector('.forecast-mapping').textContent = tr().mapping;
  $('plate').setAttribute('aria-label', tr().plate);
  $('reserve').textContent = tr().reserve + ' ' + grams(state.safety_margin_g) + ' ' + tr().per;
  if (!entries.some(e => e.source === selected)) selected = state.latest || (entries[0] || {}).source;
  $('no-debit').textContent = tr().noDebit;
  const plateLabel = e => tr().plate + ' ' + e.label.split(' ').pop();
  const picker = $('plate'); picker.replaceChildren();
  for (const entry of entries) { const option = document.createElement('option'); option.value = entry.source; option.textContent = plateLabel(entry); picker.append(option); }
  picker.value = selected || ''; picker.hidden = entries.length < 2;
  $('single').hidden = entries.length !== 1; $('single').textContent = entries.length === 1 ? plateLabel(entries[0]) : '';
  const entry = entries.find(e => e.source === selected);
  $('time').textContent = entry ? new Date(entry.observed_at * 1000).toLocaleString(currentLang || 'en') : '';
  $('status').textContent = entry ? (entry.shortage ? '✕ ' + tr().shortage : '✓ ' + tr().enough) : tr().waiting;
  $('status').style.color = entry && entry.shortage ? '#ffab91' : '#82dfb0';
  paintHeads();
 }
 $('plate').onchange = () => { selected = $('plate').value; render(); };
 $('hide').onclick = () => window.pywebview && window.pywebview.api.hide();
 window.refreshSliceForecast = async function(selectLatest = false) {
  try {
   const response = await fetch('/api/forecast', {cache:'no-store'}); if (!response.ok) throw Error('forecast unavailable');
   const next = await response.json(); const changed = next.revision !== revision;
   state = next;
   if (selectLatest) selected = next.latest;
   if (changed) { selected = next.latest; revision = next.revision; setView('overview'); }
   const nextSignature = JSON.stringify([next, currentLang]);
   if (nextSignature !== signature) { signature = nextSignature; render(); }
   $('error').textContent = next.error || '';
  } catch (e) { $('error').textContent = tr().error; }
 };
 refreshSliceForecast(); setInterval(refreshSliceForecast, 500);
})();
</script>
"""

def install(html, lab=True):
    anchor = '<aside class="sidebar" aria-labelledby="sidebar-title">'
    assert anchor in html
    markup, script = MARKUP, SCRIPT
    if not lab:
        markup = markup.replace('#nav-sender,.overview-card {display:none!important}', '')
        script = script.replace('   if (!row) return;', '   if (!row || state.printing) return;')
        script = script.replace("baseRenderSidebar(data); paintHeads();", "baseRenderSidebar(data); if (state) {state.printing = ['printing','paused'].includes((data.monitor || {}).state);} paintHeads();")
        script = script.replace("if (changed) { selected = next.latest; revision = next.revision; setView('overview'); }", "if (changed) { selected = next.latest; revision = next.revision; }")
    html = html.replace(anchor, markup + anchor, 1)
    html = html.replace('</body>', script + '</body>', 1)
    return html.replace('<title>', '<title>ТЕСТОВЫЙ ПРОГНОЗ · ', 1) if lab else html
