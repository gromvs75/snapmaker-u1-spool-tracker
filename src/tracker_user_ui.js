/* User shell. Accounting endpoints remain owned by the 2.0 SQLite queue. */
const headBoard=$('headBoard'),originalRenderWorkspace=renderWorkspace,originalLoad=load;
let selectedPrinter='',viewedPlate='',overviewSignature='';
const userNav=document.querySelector('.topnav');userNav.replaceChildren();
for(const [id,label,fn] of [['navOverview','Обзор',()=>showWorkspace('overview')],['navLibrary','Катушки',()=>showWorkspace('library')],['navHistory','История',()=>showWorkspace('history')],['navSettings','Настройки',()=>showWorkspace('settings')]]){const b=button(label,fn);b.id=id;userNav.append(b)}
const userHeader=document.querySelector('header');const userBrand=document.createElement('div');userBrand.className='user-brand';const logo=document.createElement('span');logo.className='u1-logo';logo.textContent='U1';const brandText=document.createElement('div');const brandTitle=document.createElement('strong');brandTitle.textContent='Snapmaker U1 Spool Tracker';const brandSub=paragraph('Учёт катушек и прогноз расхода для Snapmaker U1 — без изменения прошивки. · '+APP_INFO.version+' · кандидат');brandText.append(brandTitle,brandSub);userBrand.append(logo,brandText);userHeader.replaceChildren(userBrand,userNav);
const switcher=document.createElement('div');switcher.className='printer-switch';const printerLabel=document.createElement('label');printerLabel.textContent='Принтер ';const picker=document.createElement('select');picker.id='activePrinter';picker.setAttribute('aria-label','Выбранный принтер');printerLabel.append(picker);switcher.append(printerLabel);const connectionText=document.createElement('small');connectionText.id='selectedConnection';switcher.append(connectionText);document.querySelector('main').prepend(switcher);
picker.onchange=async()=>{try{selectedPrinter=picker.value;await api('settings',{values:{selected_printer:selectedPrinter},expected_revision:state.settings.revision});await refreshWorkspace()}catch(e){$('workspaceError').textContent=e.message}};
function syncPrinter(){const saved=selectedPrinter||state.settings.values.selected_printer;picker.replaceChildren();for(const p of state.printers)picker.add(new Option(p.name,p.id));selectedPrinter=state.printers.some(p=>p.id===saved)?saved:(state.printers[0]?.id||'');picker.value=selectedPrinter;connectionText.textContent=state.printers.find(p=>p.id===selectedPrinter)?.ready?'На связи':'Подключения остановлены / нет связи';}
showWorkspace=(view,tab)=>{document.body.classList.remove('autofix-page');workspaceView=view;workspaceTab=tab||({overview:'Обзор',library:'Библиотека',heads:'Головки T0–T3',settings:'Принтер',history:'История'}[view]);if(headBoard.parentNode===$('workspaceBody'))document.querySelector('main').append(headBoard);headBoard.hidden=true;$('workspace').hidden=false;$('workspace').classList.toggle('single',['overview','history'].includes(view));$('workspaceNav').replaceChildren();for(const label of view==='settings'?['Принтер','Spoolman','Учёт','Резервная копия']:['library','heads'].includes(view)?['Библиотека','Головки T0–T3']:[]){const b=button(label,()=>label==='Головки T0–T3'?showHeads():showWorkspace(view==='heads'?'library':view,label));b.setAttribute('aria-current',String(label===workspaceTab));$('workspaceNav').append(b)}for(const b of userNav.children)b.setAttribute('aria-current',b.id===({overview:'navOverview',library:'navLibrary',heads:'navLibrary',history:'navHistory',settings:'navSettings'}[view])?'page':'false');renderWorkspace()};
showHeads=()=>showWorkspace('heads');
renderWorkspace=()=>{if(!state||!workspaceView)return;if(headBoard.parentNode===$('workspaceBody')){document.querySelector('main').append(headBoard);headBoard.hidden=true}if(workspaceView==='overview'){$('workspaceTitle').textContent='Обзор';$('workspaceBody').replaceChildren();renderOverview($('workspaceBody'));return}if(workspaceView==='heads'){$('workspaceTitle').textContent='Головки T0–T3';$('workspaceBody').replaceChildren(headBoard);headBoard.hidden=false;headBoard.querySelector('h2').hidden=true;return}originalRenderWorkspace();if(workspaceView==='settings'&&['Spoolman','Отправки'].includes(workspaceTab)){const tabs=document.createElement('div');tabs.className='actions';tabs.append(button('Каталог и подключение',()=>showWorkspace('settings','Spoolman')),button('Передача расхода',()=>showWorkspace('settings','Отправки')));$('workspaceBody').prepend(tabs);$('workspaceNav').querySelectorAll('button').forEach(b=>b.setAttribute('aria-current',String(b.textContent==='Spoolman')))}if(workspaceView==='settings'&&workspaceTab==='Учёт'){const values=state.settings.values;$('workspaceBody').append(inputField('Каталог завершённых нарезок Snorca','sliceRoot',values.slice_root||state.forecast?.watch_root||''),button('Сохранить каталог нарезки',async()=>{await api('settings',{values:{slice_root:$('sliceRoot').value},expected_revision:state.settings.revision});await refreshWorkspace()}),paragraph('Прогноз обнаруженной нарезки не меняет план уже начатой печати.'))}if(workspaceView==='settings'&&workspaceTab==='Учёт'){const margin=inputField('Резерв на используемую катушку, г','safetyMargin',state.settings.values.safety_margin_g??5,'number');margin.querySelector('input').step='0.001';margin.querySelector('input').min='0';$('workspaceBody').prepend(margin,button('Сохранить резерв',async()=>{await api('settings',{values:{safety_margin_g:$('safetyMargin').value},expected_revision:state.settings.revision});await refreshWorkspace()}))}if(workspaceView==='settings')$('workspaceBody').append(paragraph('Кандидат '+APP_INFO.version+' · коммит '+APP_INFO.commit+(APP_INFO.dirty?' · изменённое дерево':'')))};
load=async(force=false)=>{await originalLoad(force);if(!state)return;syncPrinter();if(!workspaceView)showWorkspace('overview');const sig=JSON.stringify([state.printers,state.spools,state.jobs,state.export_plans,state.forecast?.entries,state.forecast?.printers,state.forecast?.safety_margin_g]);if(workspaceView==='overview'&&sig!==overviewSignature){overviewSignature=sig;renderWorkspace()}};
function panel(title){const e=document.createElement('section');e.className='overview-panel';const h=document.createElement('h3');h.textContent=title;e.append(h);return e}
function overviewJob(job){showWorkspace('history');openSavedHistory($('historyDetail'),job,true)}
function renderOverview(body){
 const jobs=state.jobs.filter(j=>j.printer_id===selectedPrinter),active=jobs.find(j=>j.state==='active');
 const last=[...jobs].reverse().find(j=>j.presentation.accounted_mg>0&&j.state!=='active');
 const exported=state.export_plans?.find(p=>p.printer_id===selectedPrinter||!p.printer_id);
 const status=panel('Состояние печати');status.classList.add('print-status');
 const title=document.createElement('strong');title.className='print-status-title';
 title.textContent=active?active.presentation.label:last?last.presentation.label:exported?'План экспорта сохранён':'Печать не наблюдается';
 status.append(title,paragraph(active?.filename||last?.filename||exported?.filename||'Ожидаем задание принтера'));
 if(active?.presentation.reason)status.append(paragraph(active.presentation.reason));
 const badge=document.createElement('span');badge.className='print-state-badge';badge.textContent=state.printers.find(p=>p.id===selectedPrinter)?.ready?'На связи':'Нет связи';status.append(badge);
 if(active&&!active.mapping_valid)status.append(button('Печать завершилась успешно?',()=>overviewJob(active)));
 if(exported){const details=document.createElement('details'),label=document.createElement('summary');label.textContent='Последняя проверка экспорта Snorca';details.append(label,paragraph(exported.filename+' · '+new Date(exported.created_at*1000).toLocaleString('ru-RU')),paragraph('План сохранён без списания. Карта головок при экспорте предполагается.'));for(const [i,w] of exported.weights.entries())if(w>0)details.append(paragraph('Материал '+(i+1)+': '+grams(w*1000)));status.append(details)}
 body.append(status);
 const forecast=panel('Прогноз после нарезки');forecast.id='sliceForecast';
 const hide=button('Скрыть в меню',()=>api('window',{action:'hide'}));hide.className='hide-to-menu';forecast.prepend(hide);
 const heads=document.createElement('div');heads.className='overview-heads';heads.id='overviewHeads';
 renderSliceForecast(forecast,heads,active);body.append(forecast,heads);
 if(active){const current=panel('План текущей печати');current.classList.add('current-print-plan');current.append(paragraph('Сохранённый план этого задания. Новая нарезка его не изменяет.'));body.append(current);
  api('history_detail',{job_key:active.job_key}).then(d=>{if(!current.isConnected)return;
    current.append(paragraph(active.filename||active.job_id));
    for(const row of d.plan)current.append(paragraph('T'+row.channel+' · '+spoolName(row.spool_id)+' · '+grams(row.planned_mg)));
    if(!d.plan.length)current.append(paragraph('План не сохранён.'));
    current.append(paragraph('Уже учтено: '+grams(d.accounted_mg)),button('Открыть задание',()=>overviewJob(active)));
    renderOverviewHeads(heads,null,d.plan);
  }).catch(e=>current.append(paragraph(e.message)));
 }
 const grid=document.createElement('div');grid.className='overview-grid';
 const accounted=panel('Последняя учтённая печать');
 if(last){accounted.append(button(last.filename||last.job_id,()=>overviewJob(last)));
   const totals={};for(const d of state.debits.filter(d=>d.job_key===last.job_key))totals[d.spool_id]=(totals[d.spool_id]||0)+d.delta_mg;
   for(const [sid,amount] of Object.entries(totals))accounted.append(paragraph(spoolName(sid)+': '+grams(amount)));
   if(last.presentation.reason)accounted.append(paragraph(last.presentation.reason));
 }else accounted.append(paragraph('Учтённых печатей пока нет.'));
 const skipped=panel('Неучтённые печати');skipped.append(paragraph('Расход этих заданий требует проверки. Уже учтённое количество сохраняется; повторное списание исключается.'));
 const pending=jobs.filter(j=>j.state==='active'&&!j.mapping_valid);
 for(const job of pending.slice(-3).reverse())skipped.append(button(job.filename||job.job_id,()=>overviewJob(job)),paragraph(job.presentation.label));
 if(!pending.length)skipped.append(paragraph('Нет заданий, требующих проверки.'));
 if(pending.length>3)skipped.append(button('Ещё '+(pending.length-3)+' — во вкладке «История»',()=>showWorkspace('history')));
 grid.append(accounted,skipped);body.append(grid);
 const delivery=state.delivery.filter(r=>!['sent','resolved'].includes(r.state)).length;
 if(delivery)body.append(button('Spoolman: требуют внимания '+delivery,()=>showWorkspace('settings','Отправки')));
}
function renderOverviewHeads(container,entry,plan=null){
 container.replaceChildren();const printer=state.forecast?.printers?.[selectedPrinter];
 for(let ch=0;ch<4;ch++){
  const row=entry?.rows?.[ch],planned=plan?.filter(p=>String(p.channel)===String(ch))||[];
  const original=planned.length?state.spools.find(s=>s.spool_id===planned[0].spool_id):null;
  const s=original||printer?.heads?.[ch]?.spool||state.spools.find(s=>{const a=assignmentFor(s);return a?.printer_id===selectedPrinter&&String(a.channel)===String(ch)});
  const box=document.createElement('section');box.className='overview-head';
  const visual=document.createElement('div');visual.className='printhead-visual';
  const circle=document.createElement('span');circle.className='printhead-color';circle.textContent='T'+ch;
  const color=s?.details?.color||'#8595a3';circle.style.background=color;
  if(/^#[0-9a-f]{6}$/i.test(color)){const n=parseInt(color.slice(1),16);circle.style.color=((n>>16)*.299+((n>>8)&255)*.587+(n&255)*.114)>155?'#12171d':'white'}
  const use=document.createElement('span');use.className='printhead-material';use.textContent=grams(plan?planned.reduce((sum,r)=>sum+r.planned_mg,0):(row?.used||0)*1000);
  visual.append(circle,use);
  if(['ok','shortage'].includes(row?.status)){const badge=document.createElement('span');badge.className='head-result '+row.status;badge.textContent=row.status==='ok'?'✓':'✕';visual.append(badge)}
  const name=document.createElement('strong');name.className='head-name';const dot=document.createElement('span');dot.className='filament-dot';dot.style.background=color;name.append(dot,document.createTextNode(s?.name||'Катушка не назначена'));
  const weight=document.createElement('strong');weight.className='head-weight';weight.textContent=s?grams(s.remaining_mg):'—';
  const result=paragraph(plan?'План текущей печати':row?.status==='ok'?'✓ Хватит':row?.status==='shortage'?'✕ Не хватит':row?.status==='unknown'?'Проверьте назначение':'Не используется');result.className='head-caption '+(row?.status||'');
  box.append(visual,name,weight,result);
  if(row?.status==='ok')box.append(paragraph('После печати ≈ '+grams(row.after*1000)));
  if(row?.status==='shortage')box.append(paragraph('Дефицит с резервом '+grams(row.deficit*1000)));
  if(row?.status==='unknown'&&row.reason)box.append(paragraph(row.reason));
  if(s?.uid){const uid=paragraph('UID '+s.uid);uid.className='head-uid';box.append(uid)}
  container.append(box);
 }
}
function renderSliceForecast(box,heads,active){
 const f=state.forecast,printer=f?.printers?.[selectedPrinter];
 const entries=printer?.entries||f?.entries||[];
 if(!entries.some(e=>e.source===viewedPlate))viewedPlate=f?.latest||entries[0]?.source||'';
 const content=document.createElement('div');box.append(content);
 const select=document.createElement('select');select.id='viewedPlate';select.setAttribute('aria-label','Стол для просмотра');
 for(const e of entries){select.add(new Option((e.plate?'Стол '+e.plate:'Стол не определён · '+e.source.split('/').pop())+(e.state==='ready'?'':' · ещё не готова'),e.source))}
 select.value=viewedPlate;select.hidden=entries.length<2;box.append(select);
 function draw(){content.replaceChildren();const e=entries.find(e=>e.source===viewedPlate);
  const title=document.createElement('strong');title.className='forecast-result '+(e?.status||'unknown');
  title.textContent=e?.state==='ready'?(e.materials?.length?'Привязка к головкам проверяется при запуске':'Нет данных о расходе материала'):e?'Нарезка ещё не готова':'Ожидаем завершённую нарезку';content.append(title);
  if(e?.state==='ready'){
   const plate=e.plate?'Стол '+e.plate:'Стол не определён';
   content.append(paragraph(plate+' · '+new Date(e.completed_at_ns/1e6).toLocaleString('ru-RU')),
     paragraph('Прогноз не списывает расход'));
   for(const material of e.materials||[])content.append(paragraph('Материал '+material.number+' · '+grams(material.grams*1000)));
   if(active)content.append(paragraph('Новая нарезка показана отдельно. Головки ниже относятся к текущей печати.'));
   if(e.source!==f.latest)content.append(paragraph('Выбрана для просмотра. В трее остаётся последняя завершённая нарезка.'));
  }else if(e)content.append(paragraph('Прежний расход не показан как актуальный: файл изменяется или удалён.'));
  const source=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Источник прогноза';
  source.append(summary,paragraph('Snorca · '+(e?.source||f?.watch_root||'Каталог не задан')));
  if(f?.error)source.append(paragraph(f.error));content.append(source);
  renderOverviewHeads(heads,active?null:e,active?[]:null);
 }
 select.onchange=()=>{viewedPlate=select.value;draw()};draw();
}
window.showLatestForecast=async()=>{await load(true);selectedPrinter=state.forecast?.selected_printer||selectedPrinter;viewedPlate=state.forecast?.latest||'';showWorkspace('overview');$('sliceForecast')?.scrollIntoView({block:'center'})};
const legacyRenderHistory=renderHistory;
renderHistory=body=>{legacyRenderHistory(body);const append=()=>{for(const row of $('historyList').querySelectorAll('[data-job]')){const job=state.jobs.find(j=>j.job_key===row.dataset.job);const estimate=row.querySelector('.review-job');if(estimate){if(!job.history_status||job.history_status==='in_progress')estimate.remove();else estimate.textContent='Оценить по истории или слою'}row.prepend(button('Раскрыть задание',()=>openSavedHistory($('historyDetail'),job)));if(job.state==='active'&&!job.mapping_valid)row.append(button('Печать завершилась успешно?',()=>openSavedHistory($('historyDetail'),job,true)))}};append();$('historyFilter').addEventListener('change',append)};
async function openSavedHistory(el,job,ask=false){const d=await api('history_detail',{job_key:job.job_key});el.replaceChildren();const h=document.createElement('h3');h.textContent=d.filename||job.job_id;el.append(h,paragraph('Первоначальный сохранённый план · доступен без слайсера и принтера'));if(d.quarantined)el.append(paragraph('План из восстановленной или изменённой копии: автоматическое списание запрещено. Значения требуют ручной проверки.'));const table=document.createElement('table');table.className='history-plan-table';table.innerHTML='<thead><tr><th>Головка</th><th>Исходная катушка</th><th>План</th><th>Уже списано с катушки</th></tr></thead>';const rows=document.createElement('tbody');for(const p of d.plan){const tr=document.createElement('tr');for(const value of ['T'+p.channel,spoolName(p.spool_id),grams(p.planned_mg),grams(d.debits.filter(v=>v.spool_id===p.spool_id).reduce((s,v)=>s+v.delta_mg,0))]){const td=document.createElement('td');td.textContent=value;tr.append(td)}rows.append(tr)}table.append(rows);el.append(table);if(!d.plan.length)el.append(paragraph('Первоначальный план отсутствует. Tracker не может восстановить его из текущей катушки.'));el.append(paragraph('Всего уже учтено: '+grams(d.accounted_mg)));for(const s of d.candidates)if(s.accounted_mg)el.append(paragraph(s.name+': '+grams(s.accounted_mg)));for(const reason of d.reasons)el.append(paragraph('Причина пропуска: '+reason));if(!d.reasons.length)el.append(paragraph(job.presentation.reason||job.presentation.label));for(const e of d.replacements)el.append(paragraph('Замена T'+e.channel+': '+(e.old_uid||'без метки')+' → '+(e.new_uid||'без метки')+' · '+(e.proven?'граница подтверждена':'граница неизвестна')));if(d.receipt)el.append(paragraph('Ручная/расчётная запись: '+(d.receipt.note||d.receipt.estimate_source)));if(job.state!=='active'||job.mapping_valid)return;
 const prompt=document.createElement('h3');prompt.textContent='Печать завершилась успешно?';el.append(prompt,paragraph('Подтверждение пользователя не заменяет историю принтера. Если принтер на связи, Tracker дополнительно проверит, что печать не продолжается.'));const editor=document.createElement('section');const choices=document.createElement('div');choices.className='actions';choices.append(button('Да — перейти к списанию',()=>manualAdditional(editor,job,d)),button('Отложить',async()=>{await api('history_decide',{job_key:job.job_key,action:'defer',expected_revision:d.revision,request_id:crypto.randomUUID()});await refreshWorkspace()}),button('Закрыть без списания',()=>{editor.replaceChildren(inputField('Печать закончена и не продолжится. Закрыть задание без дополнительного списания.','closeHistoryAck','','checkbox'),button('Подтвердить закрытие без списания',async()=>{await api('history_decide',{job_key:job.job_key,action:'close',expected_revision:d.revision,request_id:crypto.randomUUID(),confirmed:$('closeHistoryAck').checked});await refreshWorkspace()}))}));el.append(choices,editor);if(ask)prompt.scrollIntoView({block:'center'});else el.scrollIntoView({block:'start'})}
function manualAdditional(el,job,d){el.replaceChildren();el.append(paragraph('Дополнительное списание сверх уже учтённых '+grams(d.accounted_mg)+'. Исправьте значения по каждой катушке.'));if(d.uncertain){el.append(paragraph('Неопределённая отправка Spoolman уже входит в локальный расход. Сначала выполните её ручную сверку в настройках.'));return}if(d.replacements.length)el.append(paragraph('Была смена катушки. Полный план нельзя отнести к первоначальной. Укажите распределение вручную.'));const fields=document.createElement('div');fields.className='recovery-allocations';const inputs=[];for(const [i,s] of d.candidates.entries()){const field=inputField(s.name+' · уже '+grams(s.accounted_mg)+' · дополнительно, г','manualExtra_'+i,s.suggested_additional_mg===null?'':s.suggested_additional_mg/1000,'number');const input=field.querySelector('input');input.step='0.001';input.min='0';input.max=s.remaining_mg/1000;if(s.reserved){input.value='0';input.disabled=true;field.append(paragraph('Занята другим заданием'))}inputs.push([input,s]);fields.append(field)}el.append(fields,inputField('Основание и исправления количества','manualExtraNote'),inputField('Печать завершилась. Катушки и дополнительный расход проверены; продолжения задания не будет.','manualExtraAck','','checkbox'));const error=paragraph('');error.id='manualExtraError';el.append(error);let payload=null;const request=crypto.randomUUID();const save=button('Подтвердить дополнительное списание',async()=>{if(inputs.some(([i])=>i.value===''||!i.validity.valid))throw Error('Заполните расход каждой катушки, включая нулевой.');const data={job_key:job.job_key,action:'account',expected_revision:d.revision,request_id:request,confirmed:$('manualExtraAck').checked,completed:$('manualExtraAck').checked,note:$('manualExtraNote').value,allocations_mg:Object.fromEntries(inputs.map(([i,s])=>[s.spool_id,Math.round(Number(i.value)*1000)]))};if(payload&&payload!==JSON.stringify(data))throw Error('Запрос уже отправлен. Повторите без изменений или заново откройте задание.');payload=JSON.stringify(data);try{await api('history_decide',data);await refreshWorkspace();$('workspaceBody').prepend(paragraph('Ручной учёт сохранён. Повторная история не спишет расход снова.'))}catch(e){error.textContent=e.message;throw e}});save.id='manualExtraApply';el.append(save,paragraph('Связанные операции Spoolman попадут на удержание. Для отправки требуется отдельное разрешение.'))}
const oldCreateEditor=createEditor;createEditor=(el,item=null)=>{oldCreateEditor(el,item);el.classList.add('compact-create')};
$('tagForm').querySelector('h3').textContent='Выберите метку';$('tagFields').querySelector('h3').textContent='Способ регистрации';for(const label of $('tagModeRow').querySelectorAll('label'))label.lastChild.textContent=label.querySelector('input').value==='new'?'Новая катушка':'Существующая';
load().catch(e=>$('workspaceError').textContent=e.message);
