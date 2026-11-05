"""Settings panel for the optional Spoolman integration; all dynamic text is escaped."""
PANEL = '''
<style>
#sm-connect {display:grid;grid-template-columns:170px minmax(0,1fr);gap:12px;align-items:center}
#sm-connect label:has(input),#sm-connect .form-inline {grid-column:1 / -1}
#sm-connect input[type=url],#sm-connect select {width:100%;box-sizing:border-box}
#sm-connect label:has(input) {display:flex;gap:10px;align-items:center;line-height:1.5}
#sm-queue button,#sm-linked button {margin:4px}
@media(max-width:650px){#sm-connect{grid-template-columns:1fr}#sm-connect>*{grid-column:1!important}}
</style>
<div class="card" id="spoolman-panel">
 <h2>Spoolman · Preview</h2>
 <p id="sm-help" class="subtitle"></p>
 <form id="sm-connect">
  <label for="sm-url" id="sm-url-label">Server URL</label>
  <input id="sm-url" type="url" placeholder="http://127.0.0.1:7912" autocomplete="off">
  <label for="sm-mode" id="sm-mode-label">Mode</label>
  <select id="sm-mode"><option value="off">Off</option><option value="read">Read only</option><option value="send">Send usage</option></select>
  <label><input id="sm-sole" type="checkbox"> <span id="sm-sole-text"></span></label>
  <div class="form-inline"><button id="sm-save" type="submit">Save</button><button id="sm-refresh" type="button">Refresh</button></div>
 </form>
 <p id="sm-status" role="status" aria-live="polite"></p>
 <form id="sm-attach" class="form-inline">
  <select id="sm-spool" aria-label="Spoolman spool"></select>
  <select id="sm-head" aria-label="Toolhead"><option value="0">T0</option><option value="1">T1</option><option value="2">T2</option><option value="3">T3</option></select>
  <button id="sm-assign" type="submit">Assign</button>
 </form>
 <p id="sm-detach-help" class="subtitle"></p>
 <div id="sm-linked"></div>
 <h3 id="sm-queue-title">Usage delivery</h3><div id="sm-queue"></div>
 <p id="sm-error" role="alert" style="color:#ffab91"></p>
</div>
'''
SCRIPT = r'''
<script>
(() => {
 const $ = id => document.getElementById('sm-' + id);
 let loaded = false, busy = false;
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
  $('help').textContent=t('Оригинальная прошивка U1. Каталог и остатки — в Spoolman; прогноз после нарезки ничего не списывает. Поддерживается 0.27.1.','Stock U1 firmware. Spoolman stores inventory; slicing only forecasts usage. Supports 0.27.1.');
  $('url-label').textContent=t('Адрес сервера','Server URL'); $('mode-label').textContent=t('Режим','Mode');
  [...$('mode').options].forEach((o,i)=>o.textContent=[t('Отключено','Off'),t('Только чтение; расход передаёт другая интеграция','Read only; another integration sends usage'),t('Tracker отправляет расход','Tracker sends usage')][i]);
  $('sole-text').textContent=t('Подтверждаю: только этот Tracker отправляет расход данного U1.','I confirm: only this Tracker sends usage for this U1.');
  $('save').textContent=t('Сохранить подключение','Save connection'); $('refresh').textContent=t('Обновить каталог','Refresh catalog'); $('assign').textContent=t('Назначить','Assign');
  $('detach-help').textContent=t('Отвязка удаляет только локальную ссылку; катушка в Spoolman остаётся. Для автономного учёта создайте локальную катушку с проверенным остатком.','Detach removes only the local link. The Spoolman spool is retained. For standalone use, create a local spool with a verified balance.');
  $('queue-title').textContent=t('Передача расхода','Usage delivery');
  $('status').textContent=s.mode==='off' ? t('Подключение выключено','Connection off') : (s.error || (s.checked_at ? t('Каталог обновлён: ','Catalog refreshed: ')+new Date(s.checked_at*1000).toLocaleString() : t('Данные ещё не получены','No data yet')));
  if(!loaded){$('url').value=s.url; $('mode').value=s.mode; loaded=true;}
  const selected=$('spool').value; $('spool').replaceChildren();
  for(const item of Object.values(s.catalog)) {if(item.archived||item.remaining_g===null)continue;const o=document.createElement('option');o.value=item.id;o.textContent='#'+item.id+' · '+item.name+' · '+item.material+' · '+item.remaining_g+' g';$('spool').append(o);}
  if([...$('spool').options].some(o=>o.value===selected))$('spool').value=selected;
  $('linked').replaceChildren();
  for(const item of data.linked){const line=document.createElement('p');line.append(document.createTextNode(item.name+' '));line.append(button(t('Отвязать','Detach'),async()=>{if(confirm(t('Отвязать катушку? Данные Spoolman не удаляются.','Detach this spool? Spoolman data is kept.')))await call('detach',{id:item.id});}));$('linked').append(line);}
  $('queue').replaceChildren();
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
 $('connect').onsubmit=e=>{e.preventDefault();actSM(async()=>{await call('configure',{url:$('url').value,mode:$('mode').value,sole_sender:$('sole').checked});loaded=false;});};
 $('refresh').onclick=()=>actSM(()=>call('refresh',{}));
 $('attach').onsubmit=e=>{e.preventDefault();actSM(()=>call('attach',{id:Number($('spool').value),slot:Number($('head').value)}));};
 document.getElementById('nav-settings').addEventListener('click',()=>refresh(true).catch(e=>$('error').textContent=e.message));
 setInterval(()=>{if(!busy)refresh().catch(e=>$('error').textContent=e.message);},3000);
})();
</script>
'''

def install(html):
    marker = '<section id="view-settings" aria-labelledby="nav-settings" hidden>'
    return html.replace(marker, marker + PANEL).replace('</body>', SCRIPT + '</body>')
