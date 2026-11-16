// Preserve 2.0 manual transfer and interrupted-job unlock inside the full shell.
(()=>{
 const t=desktopText,dialog=node('dialog');dialog.id='desktop-operation-dialog';dialog.className='inventory-dialog';document.body.append(dialog);
 const button=(id,title,fn)=>{const b=node('button',title);b.id=id;b.type='button';b.onclick=()=>act(fn);return b};
 const close=()=>button('',t('Закрыть','Close','Schließen','Закрити','Cerrar'),()=>dialog.close());
 const transferTitle=()=>t('Перенести катушку','Transfer spool','Spule verschieben','Перенести котушку','Transferir bobina');
 const unlockTitle=()=>t('Разрешить прерванное задание','Resolve interrupted job','Unterbrochenen Auftrag klären','Вирішити перерване завдання','Resolver trabajo interrumpido');
 const loaded=window.desktopInventoryLoaded;
 window.desktopInventoryLoaded=d=>{loaded(d);for(const row of document.querySelectorAll('#spools-table tr')){
  const sid=row.dataset.spoolId,assignment=d.observations.find(r=>r.identity_mode==='manual'&&r.spool_id===sid);
  if(assignment)row.lastElementChild.append(button('desktop-transfer-'+sid,transferTitle(),()=>transfer(d,assignment)));
 }};
 function transfer(d,a){
  const target=node('select'),head=node('select');target.id='desktop-transfer-printer';head.id='desktop-transfer-head';
  for(const p of d.printers){const o=node('option',p.name);o.value=p.id;target.append(o)}target.value=d.printers.find(p=>p.id!==a.printer_id)?.id||a.printer_id;
  for(let i=0;i<4;i++){const o=node('option','T'+i);o.value=String(i);head.append(o)}
  const id=crypto.randomUUID();let submitted=null;
  dialog.replaceChildren(close(),node('h2',transferTitle()),node('p',(d.spools[a.spool_id]?.name||a.spool_id)+' · '+(d.printers.find(p=>p.id===a.printer_id)?.name||a.printer_id)+' / T'+a.channel+' →'),target,head);
  dialog.append(button('desktop-transfer-apply',t('Подтвердить физический перенос','Confirm physical transfer','Physisches Verschieben bestätigen','Підтвердити фізичний перенос','Confirmar traslado físico'),async()=>{
   const request={spool_id:a.spool_id,source_printer:a.printer_id,source_channel:a.channel,target_printer:target.value,target_channel:head.value,expected_version:a.version,request_id:id,confirmed:true};
   const raw=JSON.stringify(request);if(submitted&&submitted!==raw)throw Error(t('Повторите запрос без изменений или откройте форму заново.','Retry unchanged or reopen the form.','Unverändert wiederholen oder Formular neu öffnen.','Повторіть без змін або відкрийте форму знову.','Reintente sin cambios o abra el formulario otra vez.'));submitted=raw;
   await desktopCore('transfer',request);dialog.close();await loadData();
  }));
  if(window.graphiteTransferDialog){dialog.dataset.sourceChannel=a.channel;window.graphiteTransferDialog(dialog,d.spools[a.spool_id],d.printers.find(p=>p.id===a.printer_id)?.name||a.printer_id,target,head,el('desktop-transfer-apply'))}
  dialog.showModal();
 }
 async function unlock(key){
  const state=await desktopCore('state'),job=state.jobs.find(j=>j.job_key===key);if(!job)throw Error('Job unavailable');
  const mode=node('select');mode.id='desktop-unlock-mode';for(const [value,title] of [['15_minutes',t('На 15 минут','For 15 minutes','Für 15 Minuten','На 15 хвилин','Durante 15 minutos')],['until_assignment',t('До подтверждения назначений','Until assignments confirmed','Bis Zuweisungen bestätigt','До підтвердження призначень','Hasta confirmar asignaciones')]]){const o=node('option',title);o.value=value;mode.append(o)}
  dialog.replaceChildren(close(),node('h2',unlockTitle()),node('p',job.filename||job.job_id),node('p',t('Закрытие не списывает пропущенный расход. Старые события больше не спишут его автоматически. Новая печать заблокирована до подтверждения назначений.','Closing does not deduct missing usage. Old events cannot deduct it automatically. A new print cannot be accounted until assignments are confirmed.','Schließen bucht fehlenden Verbrauch nicht ab. Alte Ereignisse buchen ihn nicht automatisch. Neue Erfassung erst nach bestätigten Zuweisungen.','Закриття не списує пропущені витрати. Старі події не спишуть їх автоматично. Новий облік — після підтвердження призначень.','Cerrar no descuenta el consumo pendiente. Los eventos antiguos no lo descontarán automáticamente. Confirme las asignaciones antes de contabilizar otra impresión.')),mode);
  const check=(id,title)=>{const label=node('label'),input=node('input');input.type='checkbox';input.id=id;label.style.cssText='display:flex;gap:10px;align-items:center;margin:14px 0';input.style.cssText='width:18px;height:18px;min-height:18px;margin:0;padding:0';label.append(input,node('span',title));dialog.append(label);return input};
  const stopped=check('desktop-unlock-stopped',t('Печать остановлена и не будет продолжена','The print stopped and will not resume','Druck beendet, keine Fortsetzung','Друк зупинено й не буде продовжено','La impresión se detuvo y no continuará'));
  const gap=check('desktop-unlock-gap',t('Принимаю закрытие без дополнительного списания','Accept closing without additional deduction','Ohne weitere Abbuchung schließen','Приймаю закриття без додаткового списання','Acepto cerrar sin descuento adicional'));
  const apply=button('desktop-unlock-apply',unlockTitle(),async()=>{if(!stopped.checked||!gap.checked)return;await desktopCore('resolve',{job_key:key,expected_version:job.resolution_version,confirmed:true,accept_unaccounted:true,mode:mode.value});dialog.close();await loadData()});apply.disabled=true;stopped.onchange=gap.onchange=()=>apply.disabled=!stopped.checked||!gap.checked;dialog.append(apply);dialog.showModal();
 }
 const base=renderHistory;renderHistory=(d,force=false)=>{base(d,force);const runs=Object.values(d.runs||{}).sort((a,b)=>b.start_time-a.start_time).slice(0,20);const rows=[...document.querySelectorAll('#history-content .history-row')];rows.forEach((row,i)=>{
  const r=runs[i];if(!r)return;
  const job=d.saved_history[r.job_key]?.job,window=r.unlock;
  if(!row.querySelector('.desktop-unlock')&&((job?.state==='active'&&!job.mapping_valid)||window?.expired)){const b=button('',unlockTitle(),()=>unlock(r.job_key));b.className='desktop-unlock';row.append(b)}
  if(window&&!window.completed&&!row.querySelector('.desktop-unlock-status')){const note=node('small',window.expired?t('Срок истёк — требуется новая проверка','Expired — review again','Abgelaufen — erneut prüfen','Строк минув — перевірте знову','Caducado — revisar de nuevo'):t('Подтвердите назначения до следующей печати','Confirm assignments before the next print','Zuweisungen vor nächstem Druck bestätigen','Підтвердьте призначення до наступного друку','Confirme asignaciones antes de imprimir'));note.className='desktop-unlock-status';row.append(note)}
 });};
})();
