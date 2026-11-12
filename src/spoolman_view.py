"""Settings panel for the optional Spoolman integration; all dynamic text is escaped."""
PANEL = '''
<style>
#spoolman-panel {padding:26px}
#sm-connect {display:grid;gap:24px}
#sm-connect [hidden],#spoolman-panel [hidden] {display:none!important}
#sm-summary {display:flex;justify-content:space-between;gap:16px;align-items:center;border:1px solid #394255;border-radius:12px;padding:16px 20px;margin:22px 0 28px;background:#131925}
#sm-saved-mode {color:#a6dca0;font-weight:650}
#sm-server {display:grid;grid-template-columns:170px minmax(0,1fr);gap:16px;align-items:center}
#sm-url {width:100%;box-sizing:border-box}
.sm-access {display:grid;gap:24px}
.sm-access h3 {margin:0 0 6px}
.sm-access p {margin:0}
.sm-toggle {display:flex;align-items:center;gap:18px;cursor:pointer;width:fit-content}
.sm-toggle input {appearance:none;-webkit-appearance:none;position:relative;flex:0 0 48px;width:48px;height:28px;min-height:28px;padding:0;box-sizing:border-box;border:1px solid #657087;border-radius:30px;background:#50596a;margin:0;cursor:pointer;transition:background .15s}
.sm-toggle input:before {content:'';position:absolute;top:3px;left:3px;width:20px;height:20px;border-radius:50%;background:white;box-shadow:0 1px 4px #0005;transition:transform .15s}
.sm-toggle input:checked {background:#3978f6;border-color:#3978f6}
.sm-toggle input:checked:before {transform:translateX(20px)}
.sm-toggle input:focus-visible {outline:3px solid #9abaff;outline-offset:4px}
.sm-toggle input:disabled {opacity:.4;cursor:not-allowed}
.sm-toggle strong {display:block;font-size:16px;line-height:1.5}
.sm-toggle small {display:block;color:var(--muted,#9ca8bc);font-size:13px;line-height:1.6}
#sm-send-row {display:grid;grid-template-columns:1fr 1fr;gap:22px;align-items:center}
#sm-sole-row {display:flex;gap:12px;align-items:flex-start;line-height:1.5}
#sm-sole {margin-top:4px;flex:none}
#sm-selection {border-top:1px solid #394255;margin-top:24px;padding-top:16px}
#sm-attach {display:grid;grid-template-columns:minmax(0,1fr) 85px auto;gap:12px}
#sm-attach select {width:100%;min-width:0}
#sm-picker {min-width:0} #sm-search {width:100%;margin:6px 0 8px} #sm-search-status {font-size:12px;color:var(--muted);margin:6px 0} #sm-spool {min-height:138px} #sm-attach {align-items:end}
#sm-history {border-top:1px solid #394255;margin-top:20px;padding-top:18px}
#sm-history summary {cursor:pointer;font-weight:600}
#sm-queue button,#sm-linked button {margin:4px}
#sm-refresh,#sm-linked button,#sm-queue button {background:#222c3e;color:#e1e8f4}
#sm-error:empty {display:none}
#sm-assign:disabled {background:#222c3e;color:var(--muted);cursor:default}
@media(max-width:650px){#sm-server,#sm-send-row{grid-template-columns:1fr}#sm-summary{align-items:flex-start;flex-direction:column}#sm-attach{grid-template-columns:1fr 85px}#sm-assign{grid-column:1/-1}#spoolman-panel{padding:20px}}
</style>
<div class="card" id="spoolman-panel">
 <h2>Spoolman · Preview</h2>
 <p id="sm-help" class="subtitle"></p>
 <div id="sm-summary"><span id="sm-mode-label"></span><span id="sm-saved-mode"></span></div>
 <form id="sm-connect">
  <div id="sm-server"><label for="sm-url" id="sm-url-label">Server URL</label>
  <input id="sm-url" type="url" placeholder="http://127.0.0.1:7912" autocomplete="off"></div>
  <div class="sm-access">
   <div><h3 id="sm-access-title"></h3><p id="sm-access-help" class="subtitle"></p></div>
   <label class="sm-toggle"><input id="sm-read" type="checkbox" role="switch" aria-labelledby="sm-read-title"><span><strong id="sm-read-title"></strong><small id="sm-read-help"></small></span></label>
   <div id="sm-send-row">
    <label class="sm-toggle"><input id="sm-send" type="checkbox" role="switch" aria-labelledby="sm-send-title"><span><strong id="sm-send-title"></strong><small id="sm-send-help"></small></span></label>
    <label id="sm-sole-row" hidden><input id="sm-sole" type="checkbox"> <span id="sm-sole-text"></span></label>
   </div>
  </div>
  <div class="form-inline"><button id="sm-save" type="submit">Save</button><button id="sm-refresh" type="button">Refresh</button></div>
 </form>
 <p id="sm-status" role="status" aria-live="polite"></p>
 <div id="sm-selection"><h3 id="sm-selection-title"></h3>
 <form id="sm-attach" class="form-inline">
  <div id="sm-picker"><label for="sm-search" id="sm-search-label"></label><input type="search" id="sm-search" autocomplete="off" aria-controls="sm-spool"><select id="sm-spool" size="5" aria-label="Spoolman spool" required></select><p id="sm-search-status" role="status" aria-live="polite"></p></div>
  <select id="sm-head" aria-label="Toolhead"><option value="0">T0</option><option value="1">T1</option><option value="2">T2</option><option value="3">T3</option></select>
  <button id="sm-assign" type="submit">Assign</button>
 </form>
 <p id="sm-detach-help" class="subtitle"></p>
 <div id="sm-linked"></div></div>
 <details id="sm-history"><summary id="sm-queue-title">Usage delivery</summary><div id="sm-queue"></div></details>
 <p id="sm-error" role="alert" style="color:#ffab91"></p>
</div>
'''
SCRIPT = r'''
<script>
(() => {
 const $ = id => document.getElementById('sm-' + id);
 let loaded = false, busy = false, savedMode = "off", catalog = [], linked = [];
 const ru = () => currentLang === 'ru';
 const t = (r,e) => ru() ? r : e;
 async function call(action, body) {
  const r = await fetch('/api/spoolman/' + action, {method:body ? 'POST':'GET', headers:{'Content-Type':'application/json'}, body:body ? JSON.stringify(body):undefined});
  const data = await r.json(); if (!r.ok) throw Error(data.error || r.status); return data;
 }
 async function actSM(fn) {
  if(busy)return; busy=true; $('error').textContent='';
  try {await fn(); await loadData(); await refresh(true);} catch(e){$('error').textContent=e.message;} finally {busy=false;}
 }
 function button(text, fn) {const b=document.createElement('button'); b.type='button'; b.textContent=text; b.onclick=()=>actSM(fn); return b;}
 async function refresh(force=false) {
  if(document.getElementById('view-settings').hidden && !force)return;
  const data=await call('status'), s=data.state;
  $('help').textContent=t('Подключается через Tracker. Установка компонентов на принтер не требуется. Каталог и остатки — в Spoolman; прогноз после нарезки ничего не списывает. Поддерживается 0.27.1.','Connects through Tracker. No components need to be installed on the printer. Spoolman stores inventory; slicing only forecasts usage. Supports 0.27.1.');
  $('url-label').textContent=t('Адрес Spoolman','Spoolman URL'); $('mode-label').textContent=t('Режим работы Tracker','Tracker mode');
  $('saved-mode').textContent=({off:t('Отключено','Off'),read:t('Только чтение','Read only'),send:t('Чтение и списание','Read and send usage')})[s.mode];
  $('access-title').textContent=t('Доступ к Spoolman','Spoolman connection');
  $('access-help').textContent=t('Выберите, что будет делать Tracker. Изменения применяются после сохранения.','Choose what Tracker does. Changes apply after saving.');
  $('read-title').textContent=t('Читать каталог и остатки','Read catalog and balances');
  $('read-help').textContent=t('Для выбора катушек и прогноза после нарезки','For spool selection and slicing forecasts');
  $('send-title').textContent=t('Передавать расход печати','Send print usage');
  $('send-help').textContent=t('Списывать филамент в Spoolman после учёта печати','Deduct filament in Spoolman after accounting for a print');
  $('selection-title').textContent=t('Катушки для T0–T3','Spools for T0–T3');
  $('sole-text').textContent=t('Подтверждаю: только этот Tracker отправляет расход данного U1.','I confirm: only this Tracker sends usage for this U1.');
  $('save').textContent=t('Сохранить настройки','Save settings'); $('refresh').textContent=t('Обновить каталог','Refresh catalog'); $('assign').textContent=t('Назначить','Assign');
  $('detach-help').textContent=t('Выберите запись Spoolman и головку T0–T3, затем нажмите «Назначить». Это не объединяет её с отдельно созданной локальной катушкой. Совпадение названий не означает одну физическую катушку. Отвязка сохраняет запись Spoolman.','Select a Spoolman record and a T0–T3 toolhead, then click Assign. This does not merge it with a separately created local spool. Matching names do not identify the same physical spool. Detaching keeps the Spoolman record.');
  $('queue-title').textContent=t('Передача расхода','Usage delivery');
  $('status').textContent=s.mode==='off' ? t('Подключение выключено','Connection off') : (s.error || (s.checked_at ? t('Каталог обновлён: ','Catalog refreshed: ')+new Date(s.checked_at*1000).toLocaleString(ru()?'ru-RU':'en-GB') : t('Данные ещё не получены','No data yet')));
  savedMode=s.mode;
  if(!loaded){$('url').value=s.url; $('read').checked=s.mode!=='off'; $('send').checked=s.mode==='send'; $('sole').checked=s.mode==='send'; loaded=true;}
  updateControls();
  linked=data.linked;
  catalog=Object.values(s.catalog).filter(item=>!item.archived&&item.remaining_g!==null);
  $('search-label').textContent=t('Найти катушку Spoolman','Find a Spoolman spool');
  $('search').placeholder=t('Название, производитель, материал или ID','Name, manufacturer, material or ID');
  renderCatalog();
  updateControls();
  $('linked').replaceChildren();
  for(const item of data.linked){const line=document.createElement('p');line.append(document.createTextNode(item.name+' '));line.append(button(t('Отвязать','Detach'),async()=>{if(confirm(t('Отвязать катушку? Данные Spoolman не удаляются.','Detach this spool? Spoolman data is kept.')))await call('detach',{id:item.id});}));$('linked').append(line);}
  $('queue').replaceChildren();
  if(Object.values(s.outbox).some(op=>['pending','sending','uncertain'].includes(op.state)))$('history').open=true;
  const labels={pending:t('Ожидает отправки','Pending'),sending:t('Отправляется','Sending'),uncertain:t('Результат неизвестен — нужна сверка','Uncertain — review required'),sent:t('Подтверждено','Confirmed'),external:t('Только чтение — не отправлено','Read only — not sent'),resolved:t('Закрыто вручную','Closed manually')};
  for(const [id,op] of Object.entries(s.outbox).reverse().slice(0,50)){
   const line=document.createElement('p');line.append(document.createTextNode('#'+op.spool_id+' · '+op.grams+' g · '+labels[op.state]+' '));
   if(['pending','uncertain'].includes(op.state)){
    for(const [action,label] of [['applied',t('Уже учтено','Already applied')],['not_applied',t('Не учтено: отправить','Not applied: send')],['cancel',t('Закрыть без отправки','Close without sending')]]){
     line.append(button(label,async()=>{const note=prompt(t('Укажите, как проверили списание. При потере ответа повтор может списать расход дважды.','Describe how you verified usage. Resending after a lost response may charge twice.'));if(!note)return;if(!confirm(label+'?'))return;await call('resolve',{id,action,note});}));
    }
   } $('queue').append(line);
  }
  if(!Object.keys(s.outbox).length)$('queue').textContent=t('Операций пока нет','No operations yet');
 }
 function renderCatalog() {
  const selected=$('spool').value,terms=$('search').value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const matches=catalog.filter(item=>{const text=[item.id,'#'+item.id,item.name,item.manufacturer,item.material].join(' ').toLocaleLowerCase();return terms.every(term=>text.includes(term));});
  $('spool').replaceChildren();
  for(const item of matches){const o=document.createElement('option');o.value=String(item.id);o.textContent='#'+item.id+' · '+item.name+' · '+item.material+' · '+item.remaining_g+t(' г',' g');$('spool').append(o);}
  $('spool').value=matches.some(item=>String(item.id)===selected)?selected:'';
  $('search-status').textContent=matches.length?t('Найдено: ','Found: ')+matches.length+t('. Выберите катушку из списка.','. Select a spool from the list.'):t('Ничего не найдено. Измените запрос.','No matches. Change your search.');
  updateControls();
  visualCatalog(matches);
 }
 function spoolArt(color) {
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 64 64');svg.setAttribute('class','sm-art');svg.setAttribute('aria-hidden','true');
  const fill=/^#[0-9a-f]{6}$/i.test(color||'')?color:'#8290a5';
  svg.innerHTML='<ellipse cx="44" cy="30" rx="13" ry="23" fill="#29384d" stroke="#94a3b8"/><path d="M19 14L43 9v43l-24 6z" fill="'+fill+'"/><path d="m22 20 19-5m-19 11 19-5m-19 11 19-5m-19 11 19-5m-19 11 19-5" stroke="#111827" opacity=".3"/><ellipse cx="20" cy="35" rx="14" ry="23" fill="#35455b" stroke="#94a3b8"/><ellipse cx="20" cy="35" rx="10" ry="18" fill="'+fill+'"/><ellipse cx="20" cy="35" rx="5" ry="9" fill="#111827" stroke="#bdc8d5" stroke-width="2"/>';
  return svg;
 }
 function visualCatalog(matches) {
  const list=$('visual-list');if(!list)return;const focusId=list.contains(document.activeElement)?document.activeElement.dataset.spoolId:null;list.replaceChildren();
  const make=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
  for(const item of matches){const b=make('button');b.type='button';b.className='sm-spool-row';b.dataset.spoolId=item.id;b.setAttribute('aria-pressed',String($('spool').value===String(item.id)));const label=make('span');label.append(make('strong',item.name),make('small',item.material+' · #'+item.id));const weight=make('span',item.remaining_g+t(' г',' g'));weight.className='sm-weight';b.append(spoolArt(item.color),label,weight);b.onclick=()=>{$('spool').value=String(item.id);const link=linked.find(x=>x.remote_id===item.id);if(link?.slots.length)$('head').value=String(link.slots[0]);renderCatalog();};list.append(b);}
  if(focusId){const target=[...list.children].find(e=>e.dataset.spoolId===focusId);target?.focus({preventScroll:true});}
  if(!matches.length)list.append(make('p',t('Катушки не найдены','No spools found')));
  const item=catalog.find(x=>String(x.id)===$('spool').value), details=$('selected-details');details.replaceChildren();
  const link=linked.find(x=>x.remote_id===item?.id),detach=$('detach-selected');detach.disabled=!link||busy;
  if(item){details.append(spoolArt(item.color),make('p',item.name),make('small',item.material+' · #'+item.id+' · '+item.remaining_g+t(' г',' g')),make('p',link?.slots.length?t('Назначена: ','Assigned: ')+link.slots.map(x=>'T'+x).join(', '):t('Не назначена','Unassigned')));}else details.append(make('p',t('Выберите катушку из списка','Select a spool')));
  detach.onclick=()=>{if(!link)return;actSM(async()=>{if(confirm(t('Отвязать катушку? Данные Spoolman не удаляются.','Detach this spool? Spoolman data is kept.')))await call('detach',{id:link.id});});};
  $('refresh-selected').disabled=savedMode==='off'||busy;
 }

 $('search').oninput=renderCatalog;
 $('spool').onchange=updateControls;
 function updateControls() {
  const read=$('read').checked, send=read&&$('send').checked;
  $('send').disabled=!read;
  $('sole-row').hidden=!send; $('sole').required=send;
  $('url').required=read;
  $('selection').hidden=savedMode==='off';
  $('refresh').disabled=savedMode==='off';
  $('assign').disabled=savedMode==='off'||!$('spool').value;
 }
 $('read').onchange=()=>{if(!$('read').checked){$('send').checked=false;$('sole').checked=false;}updateControls();};
 $('send').onchange=()=>{$('sole').checked=false;updateControls();};
 $('connect').onsubmit=e=>{e.preventDefault();actSM(async()=>{await call('configure',{url:$('url').value,mode:!$('read').checked?'off':$('send').checked?'send':'read',sole_sender:$('sole').checked});loaded=false;window.reportSettingsSaved?.();});};
 $('refresh').onclick=()=>actSM(()=>call('refresh',{}));
 $('attach').onsubmit=e=>{e.preventDefault();if(!$('spool').value)return;if(!confirm(t('Назначить выбранную катушку на ','Assign selected spool to ')+'T'+$('head').value+'?'))return;actSM(()=>call('attach',{id:Number($('spool').value),slot:Number($('head').value)}));};
 window.refreshSpoolmanAfterRestore=async()=>{loaded=false;await refresh(true);};
 document.getElementById('nav-settings').addEventListener('click',()=>refresh(true).catch(e=>$('error').textContent=e.message));
 setInterval(()=>{if(!busy)refresh().catch(e=>$('error').textContent=e.message);},3000);
})();
</script>
'''

def install(html):
    marker = '<section id="view-settings" aria-labelledby="nav-settings" hidden>'
    return html.replace(marker, marker + PANEL).replace('</body>', SCRIPT + '</body>')
