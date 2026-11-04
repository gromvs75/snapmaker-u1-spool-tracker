"""Embedded sender screen: no external assets or browser storage."""
PANEL = '''
<section id="view-sender" aria-labelledby="nav-sender" hidden>
  <div class="card sender-panel">
    <div class="sender-heading"><div><p class="sender-eyebrow">TRACKER · 1.2 ALPHA</p>
    <h2>Отправка G-code</h2></div><span class="sender-badge">Тестовый сервер</span></div>
    <p class="subtitle">Проверьте материалы, загрузите файл и отдельно подтвердите запуск.</p>
    <p id="sender-endpoint" class="subtitle"></p>
    <ol class="sender-steps"><li>1 · Файл</li><li>2 · Проверка</li><li>3 · Загрузка</li><li>4 · Запуск</li></ol>
    <div class="sender-file"><p><strong>G-code из Snorca</strong></p><label class="sender-file-picker" for="sender-file" tabindex="0">Выбрать файл .gcode</label>
    <input type="file" id="sender-file" class="visually-hidden" accept=".gcode"><p id="sender-filename">Файл ещё не выбран</p>
    <small>Один .gcode до 32 МБ. Выбор файла ничего не отправляет на сервер.</small></div>
    <fieldset id="sender-mapping"><legend>Материал в файле → физическая головка</legend>
    <div class="sender-map-grid">''' + ''.join(f'''<label>Материал {i+1}<select id="sender-map-{i}" aria-label="Головка для материала {i+1}">''' + ''.join(f'<option value="{j}"'+(' selected' if i == j else '')+f'>T{j}</option>' for j in range(4)) + '</select></label>' for i in range(4)) + '''</div></fieldset>
    <div id="sender-report"></div>
    <div class="sender-state" role="status" aria-live="polite"><strong id="sender-status">Подключение…</strong>
    <p id="sender-help"></p></div>
    <details id="sender-details" hidden><summary>Подробности отказа</summary><pre id="sender-reason"></pre></details>
    <div class="sender-actions"><button id="sender-check" type="button" disabled>Проверить файл</button>
    <button id="sender-upload" type="button" disabled>Загрузить без запуска</button>
    <button id="sender-start" type="button" disabled>Запустить на тестовом сервере</button></div>
    <div id="sender-confirm" class="sender-confirm" hidden><h3>Запустить это задание?</h3>
    <p id="sender-confirm-text"></p><p>Проверка файла и остатков будет выполнена ещё раз. Это локальный стенд, реальный U1 не подключён.</p>
    <button id="sender-confirm-yes" type="button">Подтвердить запуск</button>
    <button id="sender-confirm-no" type="button">Отмена</button></div>
  </div>
</section>
'''
STYLE = '''<style>
.sender-heading h2{font-size:24px;text-transform:none;letter-spacing:0;margin:8px 0 0}.sender-file-picker{display:inline-block;width:fit-content;padding:10px 16px;border:1px solid #7faca5;border-radius:8px;cursor:pointer}.sender-file:has(input:disabled) .sender-file-picker{opacity:.4;pointer-events:none}.sender-state[data-tone="warning"]{border-color:#e5bb78;background:#e5bb780b}.sender-panel{max-width:960px;margin:auto}.sender-heading{display:flex;align-items:center;justify-content:space-between;gap:20px}.sender-eyebrow{font-size:11px;letter-spacing:.12em;color:#8da8b0}.sender-badge{border:1px solid #547479;background:#20363a;color:#b7e3dd;border-radius:20px;padding:6px 12px;font-size:12px;white-space:nowrap}.sender-steps{display:flex;gap:12px;list-style:none;padding:0;margin:28px 0;color:#a6b7bd;flex-wrap:wrap}.sender-steps li{padding:8px 14px;background:#ffffff08;border-radius:8px}.sender-file{border:1px dashed #637480;background:#ffffff04;border-radius:12px;padding:24px;display:grid;gap:12px}.sender-file label{font-weight:600}.sender-file small{color:#a6b7bd}.sender-file p{overflow-wrap:anywhere;margin:0}#sender-mapping{border:0;padding:0;margin:24px 0}#sender-mapping legend{margin-bottom:12px}.sender-map-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.sender-map-grid label{display:grid;gap:8px}.sender-state{border-left:3px solid #73bcb2;padding:14px 18px;background:#ffffff05;margin:20px 0}.sender-state p{margin:8px 0 0;color:#adb9c6}.sender-actions{display:flex;gap:12px;flex-wrap:wrap}.sender-actions button:last-child{background:#9ad8c8;color:#152724}.sender-actions button:disabled{opacity:.38;cursor:not-allowed}.sender-confirm{border:1px solid #709b93;border-radius:12px;padding:20px;margin-top:20px}#sender-reason{white-space:pre-wrap;overflow-wrap:anywhere}#sender-report{overflow-x:auto}#sender-report table{width:100%;font-size:14px}#sender-report th,#sender-report td{text-align:left;padding:12px 8px}button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid #a5e2d3;outline-offset:3px}@media(max-width:650px){.sender-map-grid{grid-template-columns:1fr 1fr}.sender-heading{align-items:flex-start;flex-direction:column}.sender-actions{flex-direction:column}.sender-actions button{width:100%}}
</style>'''
SCRIPT = '''<script>
(()=>{
 const $=id=>document.getElementById('sender-'+id); let state=null, dirty=false, localBusy=false, localError='';
 const labels={empty:['Выберите файл','Проверка доступна после выбора G-code.'],selected:['Файл выбран','Укажите головки и проверьте остатки материала.'],checking:['Проверяем файл…','Отправка пока недоступна.'],checked:['Проверка пройдена','Можно загрузить файл без запуска печати.'],uploading:['Загружаем и сверяем файл…','Не закрывайте окно до получения результата.'],sent:['Файл загружен и проверен','Печать ещё не запущена. Запуск требует отдельного подтверждения.'],starting:['Запрашиваем запуск…','Не повторяйте действие. Ожидаем подтверждение сервера.'],active:['Запуск подтверждён','Сервер подтвердил файл и соответствие головок. Повторный запуск заблокирован.'],blocked:['Проверка или отправка заблокирована','Проверьте назначение катушек, материал и доступный остаток.'],uploaded_blocked:['Запуск заблокирован','Файл загружен, но последующая проверка не прошла. Автоматического запуска не будет.'],outcome_unknown:['Исход запуска неизвестен','Сервер мог принять команду. Не запускайте повторно; требуется проверка состояния задания.'],upload_unknown:['Исход загрузки неизвестен','Запуск не разрешён. Требуется проверка состояния сервера.'],start_requested:['Запрос старта записан','Процесс был прерван. Повторная отправка заблокирована.'],preparing_start:['Требуется проверка задания','Подготовка старта была прервана. Повторный запуск заблокирован.']};
 async function call(path,body){const r=await fetch('/api/sender/'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||'Запрос не выполнен');return d;}
 function render(s){document.getElementById('nav-sender').hidden=s.enabled===false;state=s;const enabled=s.enabled!==false,busy=s.busy||localBusy;const text=labels[s.state]||['Требуется проверка','Действия заблокированы до выяснения состояния.'];$('status').textContent=enabled?text[0]:'Тестовая отправка недоступна';$('help').textContent=enabled?text[1]:'Запустите отдельный стенд: python spool_tracker.py --sender-demo. Настройки основного Tracker не используются.';$('endpoint').textContent=enabled?'Локальный стенд · '+s.endpoint:'';$('filename').textContent=s.filename||'Файл ещё не выбран';$('file').disabled=!enabled||busy||!['empty','selected','checked','blocked','sent'].includes(s.state);$('mapping').disabled=!enabled||busy||!['selected','checked','blocked'].includes(s.state);$('check').disabled=!enabled||busy||!['selected','checked','blocked'].includes(s.state);$('upload').disabled=!enabled||busy||dirty||s.state!=='checked'||!!localError;$('start').disabled=!enabled||busy||s.state!=='sent'||!!localError;document.querySelector('.sender-state').dataset.tone=['blocked','uploaded_blocked','outcome_unknown','upload_unknown','start_requested','preparing_start'].includes(s.state)?'warning':'normal';if(localError){$('status').textContent='Действие не выполнено';$('help').textContent=localError;}$('details').hidden=!s.reason;$('reason').textContent=s.reason||''; if(!dirty&&s.mapping)s.mapping.forEach((v,i)=>$('map-'+i).value=v);
 const rows=s.rows||[];const root=$('report');root.replaceChildren();if(rows.length){const table=document.createElement('table');const head=document.createElement('tr');for(const title of ['Головка / катушка','Нужно с резервом','Осталось','Проверка']){const th=document.createElement('th');th.textContent=title;head.append(th);}table.append(head);for(const row of rows){const tr=document.createElement('tr');const ok=['ok','unused'].includes(row.status)&&['match','unused'].includes(row.material_status);for(const value of [row.tool+' · '+(row.spool_name||'не назначена'),row.check_g+' г',row.remaining_g===null?'—':row.remaining_g+' г',row.status==='unused'?'Не используется':ok?'Достаточно':'Требует внимания']){const td=document.createElement('td');td.textContent=value;tr.append(td);}table.append(tr);}root.append(table);}}
 async function perform(fn){localError='';localBusy=true;if(state)render(state);try{render(await fn());}catch(e){localError=e.message;$('status').textContent='Действие не выполнено';$('help').textContent=e.message;}finally{localBusy=false;await refresh();}}
 async function refresh(){try{render(await call('status'));}catch(e){$('status').textContent='Связь с Tracker потеряна';$('help').textContent='Обновите страницу. Не повторяйте запуск, пока не проверено его состояние.';for(const id of ['check','upload','start','confirm-yes'])$(id).disabled=true;}}
 $('file').addEventListener('change',()=>{const file=$('file').files[0];if(!file)return;perform(async()=>{if(file.size>32*1024*1024)throw Error('Максимальный размер — 32 МБ');const content=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=reject;r.readAsDataURL(file);});dirty=false;$('confirm').hidden=true;return call('select',{filename:file.name,content});});});
 for(let i=0;i<4;i++)$('map-'+i).addEventListener('change',()=>{dirty=true;render(state);});
 $('check').onclick=()=>perform(async()=>{dirty=false;return call('check',{mapping:[0,1,2,3].map(i=>Number($('map-'+i).value))});});
 $('upload').onclick=()=>perform(()=>call('upload',{}));
 $('start').onclick=()=>{$('confirm-text').textContent=state.filename+' · '+state.endpoint;$('confirm').hidden=false;$('confirm-yes').focus();};
 $('confirm-no').onclick=()=>{$('confirm').hidden=true;$('start').focus();};
 $('confirm-yes').onclick=()=>{$('confirm').hidden=true;perform(()=>call('start',{confirmed:true}));};
 document.querySelector('.sender-file-picker').addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();if(!$('file').disabled)$('file').click();}});
 refresh();setInterval(refresh,800);
})();
</script>'''


def install(html):
    html = html.replace('<button type="button" data-view="settings"', '<button type="button" data-view="sender" id="nav-sender">Отправка</button>\n      <button type="button" data-view="settings"', 1)
    html = html.replace('<section id="view-settings"', PANEL + '\n<section id="view-settings"', 1)
    html = html.replace("['overview', 'spools', 'history', 'settings']", "['overview', 'spools', 'history', 'settings', 'sender']")
    return html.replace('</head>', STYLE+'</head>', 1).replace('</body>', SCRIPT+'</body>', 1)
