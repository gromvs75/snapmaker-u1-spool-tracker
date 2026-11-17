// Tester scenarios are added to the original history view. Accounting remains
// exclusively in HistoryReview; this file never computes physical consumption.
(()=>{
 const baseChangeLang=changeLang;
 changeLang=async language=>{await baseChangeLang(language);await window.refreshSliceForecast?.(false)};
 const text=(ru,en,de=en,uk=en,es=en)=>({ru,en,de,uk,es}[currentLang]||en);
 const weight=mg=>displayGrams(mg/1000)+(currentLang==='ru'||currentLang==='uk'?' г':' g');
 const base=renderHistory;
 const dialog=document.createElement('dialog');dialog.id='uid-history-dialog';dialog.className='inventory-dialog';document.body.append(dialog);
 const historyButton=(caption,callback)=>{const b=node('button',caption,'uid-history-secondary');b.type='button';b.onclick=()=>act(callback);return b};
 const labels={
  expand:()=>text('Раскрыть задание','Expand job','Auftrag anzeigen','Розкрити завдання','Desplegar trabajo'),
  ask:()=>text('Печать завершилась успешно?','Did the print finish successfully?','Wurde der Druck erfolgreich abgeschlossen?','Друк завершився успішно?','¿La impresión terminó correctamente?'),
  later:()=>text('Отложить','Later','Später','Відкласти','Más tarde'),
  close:()=>text('Закрыть без списания','Close without deduction','Ohne Abbuchung schließen','Закрити без списання','Cerrar sin descuento'),
  review:()=>text('Да — проверить списание','Yes — review deduction','Ja — Abbuchung prüfen','Так — перевірити списання','Sí — revisar descuento'),
  confirm:()=>text('Подтвердить дополнительное списание','Confirm additional deduction','Zusätzliche Abbuchung bestätigen','Підтвердити додаткове списання','Confirmar descuento adicional')
 };
 async function detail(key){return api('/api/history_detail',{job_key:key})}
 async function decide(payload){await api('/api/history_decide',payload);dialog.close();await loadData()}
 function field(title,type,value=''){const label=node('label',title),input=node('input');input.type=type;input.value=value;label.append(input);dialog.append(label);return input}
 function actions(...buttons){const group=node('div',undefined,'uid-history-actions');group.append(...buttons);dialog.append(group);return group}
 function primary(button){button.className='uid-history-primary';return button}
 function reasonText(reason){
  const known={'Computer slept':['Компьютер переходил в сон.','Computer slept.','Computer war im Ruhezustand.','Комп’ютер переходив у сон.','El equipo entró en reposo.'],'Motion lifecycle restarted':['Наблюдение за расходом перезапущено.','Usage observation restarted.','Verbrauchsbeobachtung neu gestartet.','Спостереження витрат перезапущено.','Se reinició el seguimiento del consumo.']};if(known[reason])return text(...known[reason]);
  if(reason==='Connection lost during pause')return text('Соединение потеряно во время паузы.','Connection lost during pause.','Verbindung während der Pause verloren.','З’єднання втрачено під час паузи.','Se perdió la conexión durante la pausa.');
  if(reason.startsWith('Automatic replenishment cannot be ruled out'))return text(
   'Нельзя исключить автозамену катушки. Исходная катушка и оценка расхода сохранены; проверьте фактическое распределение перед списанием.',
   'Automatic spool replacement cannot be ruled out. The original spool and estimate are saved; verify the actual allocation before deducting.',
   'Ein automatischer Spulenwechsel ist nicht ausgeschlossen. Ursprüngliche Spule und Schätzung sind gespeichert; die tatsächliche Verteilung vor der Abbuchung prüfen.',
   'Не можна виключити автозаміну котушки. Початкову котушку й оцінку збережено; перед списанням перевірте фактичний розподіл.',
   'No se puede descartar un cambio automático de bobina. Se guardaron la bobina original y la estimación; verifique el reparto real antes de descontar.');
  return reason;
 }
 function view(d,data){
  const heading=node('div',undefined,'uid-history-heading'),close=historyButton(text('Закрыть','Close','Schließen','Закрити','Cerrar'),()=>dialog.close());
  heading.append(node('h2',d.filename||d.job.job_id),close);dialog.replaceChildren(heading);
  const status=d.job.state==='resolved'?text('Закрыто без дополнительного списания','Closed without additional deduction','Ohne weitere Abbuchung geschlossen','Закрито без додаткового списання','Cerrado sin descuento adicional'):
   d.review_block==='already_accounted'?text('Учёт завершён','Accounting completed','Erfassung abgeschlossen','Облік завершено','Contabilización finalizada'):
   d.review_block==='observing'?text('Печать наблюдается','Print being observed','Druck wird beobachtet','Друк спостерігається','Impresión en seguimiento'):
   text('Требуется проверка расхода','Usage review required','Verbrauch prüfen','Потрібна перевірка витрат','Revisar consumo');
  dialog.append(node('p',status,'uid-history-state'));
  dialog.append(node('p',text('Сохранённый план — без слайсера и подключения к принтеру','Saved plan — no slicer or printer connection required','Gespeicherter Plan — ohne Slicer oder Druckerverbindung','Збережений план — без слайсера та підключення до принтера','Plan guardado — sin necesidad del laminador ni conexión a la impresora')));
  const table=node('table');table.className='uid-saved-plan';const header=node('tr');
  for(const caption of [text('Головка','Toolhead','Druckkopf','Голівка','Cabezal'),text('Исходная катушка','Original spool','Ursprüngliche Spule','Початкова котушка','Bobina original'),text('План','Plan'),text('Уже учтено с катушки','Already accounted per spool','Bereits je Spule erfasst','Вже враховано з котушки','Ya contabilizado por bobina')])header.append(node('th',caption));
  table.append(header);
  for(const p of d.plan){const row=node('tr'),used=d.debits.filter(v=>v.spool_id===p.spool_id).reduce((sum,v)=>sum+v.delta_mg,0);for(const v of [p.mapping_verified===false?text('Материал ','Material ','Material ','Матеріал ','Material ')+(p.logical_tool+1)+' (?)':'T'+p.channel,data.spools[p.spool_id]?.name||p.spool_id||'—',weight(p.planned_mg),weight(used)])row.append(node('td',v));table.append(row)}
  dialog.append(table);
  if(!d.plan.length)dialog.append(node('p',text('План не сохранён. Его нельзя восстановить из текущего назначения.','No saved plan. Current assignments cannot reconstruct it.','Kein gespeicherter Plan. Aktuelle Zuweisungen können ihn nicht rekonstruieren.','План не збережено. Поточні призначення не дозволяють його відновити.','No hay plan guardado. Las asignaciones actuales no permiten reconstruirlo.')));
  dialog.append(node('p',text('Всего уже учтено: ','Already accounted: ','Bereits erfasst: ','Всього вже враховано: ','Ya contabilizado: ')+weight(d.accounted_mg)));
  for(const reason of d.reasons)dialog.append(node('p',text('Причина пропуска: ','Reason for review: ','Prüfgrund: ','Причина пропуску: ','Motivo de revisión: ')+(reason==='legacy_import_review'?text('История перенесена из 1.x. Перед дополнительным списанием проверьте план и возможные замены катушек.','History imported from 1.x. Verify the plan and any spool changes before an additional deduction.','Verlauf aus 1.x übernommen. Vor weiteren Abbuchungen Plan und mögliche Spulenwechsel prüfen.','Історію перенесено з 1.x. Перед додатковим списанням перевірте план і можливі заміни котушок.','Historial importado de 1.x. Verifique el plan y los cambios de bobina antes de un descuento adicional.'):reasonText(reason))));
  if(d.replacements.length)dialog.append(node('p',text('Была замена катушки. Весь первоначальный план нельзя списать с прежней катушки.','A spool was replaced. The full original plan cannot be deducted from the original spool.','Eine Spule wurde gewechselt. Der ganze ursprüngliche Plan darf nicht von der alten Spule abgebucht werden.','Котушку замінили. Не можна списати весь початковий план зі старої котушки.','Se sustituyó una bobina. No se puede descontar todo el plan de la bobina original.')));
  if(d.quarantined)dialog.append(node('p',text('План из восстановленной копии требует проверки.','The restored plan requires review.','Der wiederhergestellte Plan muss geprüft werden.','Відновлений план потребує перевірки.','El plan restaurado requiere revisión.')));
 }
 async function open(key,data,ask=false){
  const d=await detail(key);view(d,data);
  if(d.can_review){
   const closed=['resolved','cancelled'].includes(d.job.state);
   dialog.append(node('h3',closed?text('Ручная корректировка расхода','Manual usage adjustment','Verbrauch manuell korrigieren','Ручне коригування витрат','Corrección manual del consumo'):labels.ask()));
   dialog.append(node('p',text('На следующем шаге выберите дополнительный расход по катушкам и исправьте значения. До подтверждения остатки не изменятся.','On the next step, review and edit the additional usage per spool. Balances stay unchanged until confirmation.','Im nächsten Schritt zusätzlichen Verbrauch je Spule prüfen und bearbeiten. Restmengen ändern sich erst nach Bestätigung.','На наступному кроці перевірте та виправте додаткові витрати за котушками. Залишки зміняться лише після підтвердження.','En el siguiente paso, revise y edite el consumo adicional por bobina. Los saldos solo cambiarán tras confirmar.'),'uid-history-help'));
   const reviewButton=primary(historyButton(closed?text('Скорректировать расход вручную','Adjust usage manually','Verbrauch manuell korrigieren','Скоригувати витрати вручну','Corregir consumo manualmente'):labels.review(),()=>edit(d,data)));reviewButton.id='uid-history-edit';
   if(closed)actions(reviewButton);
   else actions(reviewButton,historyButton(labels.later(),()=>decide({job_key:key,action:'defer',expected_revision:d.revision,request_id:crypto.randomUUID()})),historyButton(labels.close(),()=>closeJob(d,data)));
  }else{
   dialog.append(node('p',d.review_block==='already_accounted'?text('Повторное списание этого задания недоступно: учёт уже завершён.','This job cannot be deducted again: accounting is complete.','Keine erneute Abbuchung: Die Erfassung dieses Auftrags ist abgeschlossen.','Повторне списання недоступне: облік завдання завершено.','No se puede descontar de nuevo: la contabilización terminó.'):
    d.review_block==='observing'?text('Ручной учёт доступен после завершения наблюдения за печатью.','Manual accounting is available once print observation ends.','Manuelle Erfassung ist nach Ende der Druckbeobachtung möglich.','Ручний облік доступний після завершення спостереження друку.','La contabilización manual estará disponible al terminar el seguimiento.'):
    text('Ручной учёт для этого состояния недоступен.','Manual accounting is unavailable for this state.','Manuelle Erfassung ist in diesem Zustand nicht verfügbar.','Ручний облік для цього стану недоступний.','La contabilización manual no está disponible en este estado.'),'uid-history-help'));
  }
  window.graphiteHistoryDialog?.(dialog);
  if(!dialog.open)dialog.showModal();
 }
 function closeJob(d,data){view(d,data);const ack=field(text('Печать закончена и не продолжится. Закрыть без дополнительного списания.','The print has ended and will not resume. Close without an additional deduction.','Der Druck ist beendet und wird nicht fortgesetzt. Ohne weitere Abbuchung schließen.','Друк завершено і не буде продовжено. Закрити без додаткового списання.','La impresión terminó y no se reanudará. Cerrar sin descuento adicional.'),'checkbox');
  dialog.append(historyButton(labels.close(),()=>{if(!ack.checked)throw Error(labels.ask());return decide({job_key:d.job.job_key,action:'close',expected_revision:d.revision,request_id:crypto.randomUUID(),confirmed:true})}));
  window.graphiteHistoryDialog?.(dialog);
 }
 function edit(d,data){view(d,data);
  if(d.uncertain){dialog.append(node('p',text('Сначала сверьте неопределённую отправку Spoolman. Этот расход уже учтён локально.','Reconcile the uncertain Spoolman delivery first. This usage is already accounted locally.','Zuerst die unklare Spoolman-Übertragung abgleichen. Dieser Verbrauch ist lokal bereits erfasst.','Спочатку звірте невизначену відправку Spoolman. Ці витрати вже враховано локально.','Primero concilie el envío incierto de Spoolman. Este consumo ya está contabilizado localmente.')));window.graphiteHistoryDialog?.(dialog);return}
  dialog.append(node('h3',text('Дополнительно списать, г','Additional deduction, g','Zusätzliche Abbuchung, g','Додатково списати, г','Descuento adicional, g')));
  const inputs=d.candidates.map(s=>{const i=field(s.name,'number',s.suggested_additional_mg===null?'':s.suggested_additional_mg/1000);i.step='0.001';i.min='0';i.max=s.remaining_mg/1000;i.dataset.spool=s.spool_id;i.className='uid-extra-amount';if(s.reserved){i.value='0';i.disabled=true}return [s,i]});
  const note=field(text('Основание и исправления','Reason and adjustments','Begründung und Korrekturen','Підстава та виправлення','Motivo y correcciones'),'text');note.id='uid-review-note';
  const ack=field(text('Печать завершилась. Катушки и дополнительный расход проверены.','The print has ended. Spools and additional usage have been verified.','Der Druck ist beendet. Spulen und zusätzlicher Verbrauch wurden geprüft.','Друк завершено. Котушки й додаткові витрати перевірено.','La impresión terminó. Se verificaron las bobinas y el consumo adicional.'),'checkbox');ack.id='uid-review-ack';
  const request=crypto.randomUUID();let submitted=null;
  const apply=historyButton(labels.confirm(),async()=>{
   if(!ack.checked||note.value.trim().length<3||inputs.some(([s,i])=>i.value===''||!i.validity.valid))throw Error(text('Проверьте значения, основание и подтверждение.','Check amounts, reason and confirmation.','Mengen, Begründung und Bestätigung prüfen.','Перевірте значення, підставу та підтвердження.','Revise cantidades, motivo y confirmación.'));
   const payload={job_key:d.job.job_key,action:'account',expected_revision:d.revision,request_id:request,confirmed:true,completed:true,note:note.value,allocations_mg:Object.fromEntries(inputs.map(([s,i])=>[s.spool_id,Math.round(Number(i.value)*1000)]))};
   const encoded=JSON.stringify(payload);if(submitted&&submitted!==encoded)throw Error(text('Запрос уже отправлен. Повторите без изменений или откройте задание заново.','Request already sent. Retry unchanged or reopen the job.'));
   submitted=encoded;await decide(payload);
  });apply.id='uid-review-apply';actions(primary(apply));dialog.append(node('p',text('Для связанной катушки Spoolman расход попадёт в очередь. Неопределённая отправка автоматически не повторяется.','For a linked Spoolman spool, usage enters the queue. Uncertain delivery is never retried automatically.','Bei verknüpften Spoolman-Spulen kommt der Verbrauch in die Warteschlange. Unklare Übertragungen werden nicht automatisch wiederholt.','Для пов’язаної котушки Spoolman витрати потраплять до черги. Невизначена відправка автоматично не повторюється.','Para bobinas de Spoolman, el consumo entra en la cola. Los envíos inciertos nunca se repiten automáticamente.')));
  window.graphiteHistoryDialog?.(dialog);
 }
 let initial=true;
 renderReviews=function(data){
  const content=el('review-content');content.replaceChildren();
  const pending=Object.values(data.runs||{}).filter(r=>!r.closed_without_deduction&&(r.status==='review'||r.status==='cancelled')).sort((a,b)=>b.start_time-a.start_time);
  content.hidden=!pending.length;
  if(!pending.length)return;
  content.append(node('h2',text('Задания для проверки','Jobs to review','Aufträge zur Prüfung','Завдання для перевірки','Trabajos para revisar')));
  content.append(node('p',text('Откройте сохранённый план и уже учтённый расход. Дополнительное списание требует подтверждения.','Review the saved plan and usage already accounted. Additional deductions require confirmation.','Gespeicherten Plan und erfassten Verbrauch prüfen. Weitere Abbuchungen müssen bestätigt werden.','Перегляньте збережений план і вже враховані витрати. Додаткове списання потребує підтвердження.','Revise el plan guardado y el consumo ya contabilizado. Los descuentos adicionales requieren confirmación.'),'subtitle'));
  for(const run of pending.slice(0,3)){
   const row=node('div',undefined,'uid-review-row');row.dataset.jobKey=run.job_key;
   const info=node('div',undefined,'uid-review-info');
   info.append(node('strong',run.filename),node('span',new Date(run.start_time*1000).toLocaleString(currentLang),'uid-review-date'),node('span',text('Уже учтено: ','Already accounted: ','Bereits erfasst: ','Вже враховано: ','Ya contabilizado: ')+displayGrams(run.accounted_g)+' '+gramUnit(),'uid-review-amount'));
   row.append(info,historyButton(labels.expand(),()=>open(run.job_key,data)));
   content.append(row);
  }
 };
 renderHistory=function(data,force=false){
  base(data,force);
  // The legacy panel only selected automatic motion/G-code records. The UID
  // ledger also contains manual, calculated and partial accounting.
  const latestBox=el('latest-accounting');latestBox.replaceChildren();
  el('latest-heading').textContent=text('Последняя учтённая печать','Latest accounted print','Zuletzt erfasster Druck','Останній врахований друк','Última impresión contabilizada');
  const latest=Object.values(data.runs||{}).sort((a,b)=>b.start_time-a.start_time).find(r=>r.accounted_g>0);
  if(latest){
   latestBox.append(node('strong',latest.filename));
   for(const [id,grams] of Object.entries(latest.accounted_by_spool||{}))latestBox.append(node('p',(data.spools[id]?.name||id)+': '+displayGrams(grams)+' '+gramUnit(),'latest-amount'));
   const label=latest.accounting_method==='legacy_import'?text('Перенесено из истории 1.x','Imported from 1.x history','Aus Verlauf 1.x übernommen','Перенесено з історії 1.x','Importado del historial 1.x'):latest.accounting_method==='manual_review'?text('Подтверждено вручную','Confirmed manually','Manuell bestätigt','Підтверджено вручну','Confirmado manualmente'):latest.accounting_method==='motion_estimate'?text('Оценка по движению','Motion estimate','Bewegungsschätzung','Оцінка за рухом','Estimación por movimiento'):text('Расчёт по сохранённому плану и истории','Estimate from saved plan and history','Berechnung aus gespeichertem Plan und Verlauf','Розрахунок за збереженим планом та історією','Cálculo del plan guardado y el historial');
   latestBox.append(node('p',label,'subtitle'));
   if(latest.status!=='committed')latestBox.append(node('p',text('Частичный учёт — требуется проверка','Partial accounting — review required','Teilweise erfasst — Prüfung erforderlich','Частковий облік — потрібна перевірка','Contabilización parcial — requiere revisión'),'subtitle'));
   latestBox.append(historyButton(labels.expand(),()=>open(latest.job_key,data)));
  }else latestBox.append(node('p',text('Учтённых печатей пока нет.','No accounted prints yet.','Noch keine erfassten Drucke.','Врахованих друків поки немає.','Todavía no hay impresiones contabilizadas.'),'subtitle'));
  const runs=Object.values(data.runs||{}).sort((a,b)=>b.start_time-a.start_time).slice(0,20);
  const rows=[...document.querySelectorAll('#history-content .history-row')];
  rows.forEach((row,i)=>{if(!runs[i])return;if(runs[i].closed_without_deduction){const badge=row.querySelector('.head-status');if(badge)badge.textContent=text('Закрыто без списания','Closed without deduction','Ohne Abbuchung geschlossen','Закрито без списання','Cerrado sin descuento')}if(row.querySelector('.uid-expand'))return;const b=historyButton(labels.expand(),()=>open(runs[i].job_key,data));b.className='uid-expand uid-history-secondary';row.append(b)});
  if(initial){initial=false;const job=runs.find(r=>['active','review'].includes(data.saved_history[r.job_key]?.job.state)&&!data.saved_history[r.job_key]?.job.mapping_valid);
   if(job)setTimeout(()=>{if(!document.querySelector('dialog[open]'))act(()=>open(job.job_key,data,true))},300);
  }
 };
 const style=node('style');style.textContent='.uid-saved-plan{width:100%;border-collapse:collapse}.uid-saved-plan td,.uid-saved-plan th{padding:10px;text-align:left;border-bottom:1px solid var(--border)}#uid-history-dialog>label{display:block;margin:15px 0}#uid-history-dialog label input{display:block;width:100%;margin-top:6px}#uid-history-dialog label input[type=checkbox]{width:auto;display:inline-block;margin-left:10px}.printhead-material{font-size:11px!important;white-space:nowrap;overflow:visible!important;text-overflow:clip!important}';style.textContent+=`
 #uid-history-dialog{width:min(820px,calc(100vw - 48px));max-width:calc(100vw - 32px);padding:24px;box-sizing:border-box;color:var(--text,#e2e8f0)}
 #uid-history-dialog .uid-history-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}
 #uid-history-dialog .uid-history-heading h2{margin:0;font-size:21px;line-height:1.35;overflow-wrap:anywhere;min-width:0}
 #uid-history-dialog .uid-history-heading button{flex-shrink:0}
 #uid-history-dialog .uid-history-actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:20px}
 #uid-history-dialog button,#review-content button,#latest-accounting button,#history-content .uid-expand{min-height:34px;padding:7px 12px;font-size:13px;line-height:1.4;white-space:normal}
 #uid-history-dialog .uid-history-secondary,#review-content button,#latest-accounting button,#history-content .uid-expand{background:#202d40;border:1px solid #43526a;color:#dce5f1}
 #uid-history-dialog .uid-history-primary{background:#2f6fd5;border:1px solid #2f6fd5;color:white}
 #uid-history-dialog .uid-history-state{display:inline-block;margin:14px 0 4px;color:#b5c9e2;font-size:13px}
 #uid-history-dialog .uid-history-help{color:#b5c2d4;font-size:13px;line-height:1.6}
 #uid-history-dialog p{line-height:1.5;overflow-wrap:anywhere}
 #uid-history-dialog .uid-saved-plan{table-layout:fixed;min-width:0;margin:18px 0}
 #uid-history-dialog .uid-saved-plan th{font-size:11px;line-height:1.4;color:#a6b5ca}
 #uid-history-dialog .uid-saved-plan td,#uid-history-dialog .uid-saved-plan th{white-space:normal;overflow-wrap:anywhere;padding:10px 8px}
 #uid-history-dialog .uid-saved-plan th:first-child{width:12%}
 #uid-history-dialog .uid-saved-plan th:nth-child(2){width:34%}
 #uid-history-dialog .uid-saved-plan th:nth-child(3){width:16%}
 #uid-history-dialog label{font-size:14px;line-height:1.5}
 #uid-history-dialog label:has(input[type=checkbox]){display:flex;align-items:flex-start;gap:10px}
 #uid-history-dialog label input[type=checkbox]{order:-1;flex-shrink:0;margin:3px 0 0;min-height:0}
 #review-content .uid-review-row{display:flex;align-items:center;justify-content:space-between;gap:20px;border-top:1px solid var(--border);padding:16px 0}
 #review-content .uid-review-info{display:grid;gap:6px;min-width:0;line-height:1.4}
 #review-content .uid-review-info strong{font-size:14px;overflow-wrap:anywhere}
 #review-content .uid-review-date{font-size:12px;color:#a6b5ca}
 #review-content .uid-review-amount{font-size:13px;color:#c7d3e3}
 #review-content .uid-review-row button{flex-shrink:0;max-width:42%}
 #review-content>.subtitle{font-size:13px;line-height:1.6;margin-bottom:20px;color:#a6b5ca}
 #latest-accounting .latest-amount{margin:6px 0}
 #latest-accounting>button{margin-top:12px}
 @media(max-width:740px){#uid-history-dialog{padding:18px}.uid-history-heading{flex-wrap:wrap}#review-content .uid-review-row{flex-wrap:wrap;gap:12px}#review-content .uid-review-row button{max-width:100%}}
 `;document.body.append(style);
})();
