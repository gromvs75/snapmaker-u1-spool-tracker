// Tester scenarios are added to the original history view. Accounting remains
// exclusively in HistoryReview; this file never computes physical consumption.
(()=>{
 const baseChangeLang=changeLang;
 changeLang=async language=>{await baseChangeLang(language);await window.refreshSliceForecast?.(false)};
 const text=(ru,en,de=en,uk=en,es=en)=>({ru,en,de,uk,es}[currentLang]||en);
 const weight=mg=>displayGrams(mg/1000)+(currentLang==='ru'||currentLang==='uk'?' г':' g');
 const base=renderHistory;
 const dialog=document.createElement('dialog');dialog.id='uid-history-dialog';dialog.className='inventory-dialog';document.body.append(dialog);
 let busy=false;
 const historyButton=(caption,callback)=>{const b=node('button',caption,'uid-history-secondary');b.type='button';b.onclick=async()=>{if(busy)return;busy=true;const buttons=[...dialog.querySelectorAll('button:not(:disabled)')];buttons.forEach(b=>b.disabled=true);try{await callback()}catch(e){let error=dialog.querySelector('#uid-history-error');if(!error){error=node('p',undefined,'gd-notice');error.id='uid-history-error';error.setAttribute('role','alert');(dialog.querySelector('.gd-body')||dialog).append(error)}error.textContent=e.message}finally{busy=false;buttons.forEach(b=>b.disabled=false)}};return b};
 dialog.addEventListener('cancel',e=>{if(busy)e.preventDefault()});
 const deliveryCaption=state=>window.desktopDeliveryCaption?.(state)||state;
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
   d.review_block==='already_accounted'?text('Учтено в Tracker','Accounted in Tracker','In Tracker erfasst','Враховано у Tracker','Contabilizado en Tracker'):
   d.review_block==='observing'?text('Печать наблюдается','Print being observed','Druck wird beobachtet','Друк спостерігається','Impresión en seguimiento'):
   text('Требуется проверка расхода','Usage review required','Verbrauch prüfen','Потрібна перевірка витрат','Revisar consumo');
  const statusBadge=node('p',status,'uid-history-state');statusBadge.dataset.state=d.review_block==='already_accounted'?'complete':d.review_block==='observing'?'active':d.job.state==='resolved'?'closed':'review';dialog.append(statusBadge);
  dialog.append(node('p',text('Сохранённый план — без слайсера и подключения к принтеру','Saved plan — no slicer or printer connection required','Gespeicherter Plan — ohne Slicer oder Druckerverbindung','Збережений план — без слайсера та підключення до принтера','Plan guardado — sin necesidad del laminador ni conexión a la impresora')));
  const table=node('table');table.className='uid-saved-plan';const header=node('tr');
  for(const caption of [text('Головка','Toolhead','Druckkopf','Голівка','Cabezal'),text('Исходная катушка','Original spool','Ursprüngliche Spule','Початкова котушка','Bobina original'),text('План','Plan'),text('Уже учтено с катушки','Already accounted per spool','Bereits je Spule erfasst','Вже враховано з котушки','Ya contabilizado por bobina')])header.append(node('th',caption));
  table.append(header);
  for(const p of d.plan){const row=node('tr'),used=d.debits.filter(v=>v.spool_id===p.spool_id).reduce((sum,v)=>sum+v.delta_mg,0);for(const v of [p.mapping_verified===false?text('Материал ','Material ','Material ','Матеріал ','Material ')+(p.logical_tool+1)+' (?)':'T'+p.channel,data.spools[p.spool_id]?.name||p.spool_id||'—',weight(p.planned_mg),weight(used)])row.append(node('td',v));table.append(row)}
  dialog.append(table);
  if(!d.plan.length)dialog.append(node('p',text('План не сохранён. Его нельзя восстановить из текущего назначения.','No saved plan. Current assignments cannot reconstruct it.','Kein gespeicherter Plan. Aktuelle Zuweisungen können ihn nicht rekonstruieren.','План не збережено. Поточні призначення не дозволяють його відновити.','No hay plan guardado. Las asignaciones actuales no permiten reconstruirlo.')));
  dialog.append(node('p',text('Всего уже учтено: ','Already accounted: ','Bereits erfasst: ','Всього вже враховано: ','Ya contabilizado: ')+weight(d.accounted_mg)));
  let notes=dialog;
  if(d.review_block==='already_accounted'){notes=node('details');notes.append(node('summary',text('Источник плана и сведения об учёте','Plan source and accounting details','Planquelle und Buchungsdetails','Джерело плану та відомості про облік','Origen del plan y detalles del registro')));dialog.append(notes)}
  for(const reason of d.reasons)notes.append(node('p',text('Причина пропуска: ','Reason for review: ','Prüfgrund: ','Причина пропуску: ','Motivo de revisión: ')+(reason==='legacy_import_review'?text('История перенесена из 1.x. Перед дополнительным списанием проверьте план и возможные замены катушек.','History imported from 1.x. Verify the plan and any spool changes before an additional deduction.','Verlauf aus 1.x übernommen. Vor weiteren Abbuchungen Plan und mögliche Spulenwechsel prüfen.','Історію перенесено з 1.x. Перед додатковим списанням перевірте план і можливі заміни котушок.','Historial importado de 1.x. Verifique el plan y los cambios de bobina antes de un descuento adicional.'):reasonText(reason))));
  if(d.replacements.length)notes.append(node('p',text('Была замена катушки. Весь первоначальный план нельзя списать с прежней катушки.','A spool was replaced. The full original plan cannot be deducted from the original spool.','Eine Spule wurde gewechselt. Der ganze ursprüngliche Plan darf nicht von der alten Spule abgebucht werden.','Котушку замінили. Не можна списати весь початковий план зі старої котушки.','Se sustituyó una bobina. No se puede descontar todo el plan de la bobina original.')));
  if(d.quarantined)notes.append(node('p',text('План из восстановленной копии требует проверки.','The restored plan requires review.','Der wiederhergestellte Plan muss geprüft werden.','Відновлений план потребує перевірки.','El plan restaurado requiere revisión.')));
 }
 async function open(key,data,ask=false){
  const run=data.runs[key];
  if(run?.status==='printer_history'){
   const close=historyButton(text('Закрыть','Close','Schließen','Закрити','Cerrar'),()=>dialog.close());
   const heading=node('div',undefined,'uid-history-heading');heading.append(node('h2',run.filename),close);
   dialog.replaceChildren(heading,node('p',new Date(run.start_time*1000).toLocaleString(currentLang)),
    node('p',text('Задание сохранено из истории принтера. Tracker не смог привязать расход к катушке. Учтено 0 г.','Saved from printer history. Tracker could not link usage to a spool. Accounted: 0 g.','Aus dem Druckerverlauf gespeichert. Der Verbrauch konnte keiner Spule zugeordnet werden. Erfasst: 0 g.','Збережено з історії принтера. Tracker не зміг прив’язати витрати до котушки. Враховано 0 г.','Guardado del historial de la impresora. Tracker no pudo asociar el consumo a una bobina. Contabilizado: 0 g.')));
   const prepare=primary(historyButton(text('Указать катушки и расход','Choose spools and usage','Spulen und Verbrauch wählen','Вказати котушки та витрати','Elegir bobinas y consumo'),async()=>{
    const draft=await api('/api/history_prepare',{history_key:key.replace(/^printer-history:/,'')});
    await loadData();const d=await detail(draft.job_key);
    if(d.can_review)edit(d,desktopFormData||data);else await open(draft.job_key,desktopFormData||data);
   }));prepare.id='uid-history-prepare';actions(prepare);
   window.graphiteHistoryDialog?.(dialog);if(!dialog.open)dialog.showModal();return;
  }
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
  if(d.remote_operations.length){const send=historyButton(text('Продолжить в Spoolman','Continue to Spoolman','Weiter zu Spoolman','Продовжити у Spoolman','Continuar a Spoolman'),()=>deliveryStep(key,data));send.id='uid-history-delivery';actions(send)}
  window.graphiteHistoryDialog?.(dialog);
  if(!dialog.open)dialog.showModal();
 }
 function closeJob(d,data){view(d,data);const ack=field(text('Печать закончена и не продолжится. Закрыть без дополнительного списания.','The print has ended and will not resume. Close without an additional deduction.','Der Druck ist beendet und wird nicht fortgesetzt. Ohne weitere Abbuchung schließen.','Друк завершено і не буде продовжено. Закрити без додаткового списання.','La impresión terminó y no se reanudará. Cerrar sin descuento adicional.'),'checkbox');
  dialog.append(historyButton(labels.close(),()=>{if(!ack.checked)throw Error(labels.ask());return decide({job_key:d.job.job_key,action:'close',expected_revision:d.revision,request_id:crypto.randomUUID(),confirmed:true})}));
  window.graphiteHistoryDialog?.(dialog);
 }
 function edit(d,data){view(d,data);
  if(d.uncertain){dialog.append(node('p',text('Сначала сверьте неопределённую отправку Spoolman. Этот расход уже учтён локально.','Reconcile the uncertain Spoolman delivery first. This usage is already accounted locally.','Zuerst die unklare Spoolman-Übertragung abgleichen. Dieser Verbrauch ist lokal bereits erfasst.','Спочатку звірте невизначену відправку Spoolman. Ці витрати вже враховано локально.','Primero concilie el envío incierto de Spoolman. Este consumo ya está contabilizado localmente.')));window.graphiteHistoryDialog?.(dialog);return}
  dialog.append(node('h3',text('Шаг 1 · Дополнительно списать, г','Step 1 · Additional deduction, g','Zusätzliche Abbuchung, g','Додатково списати, г','Descuento adicional, g')));
  const inputs=[];
  function amount(s){const i=field(s.name,'number',s.suggested_additional_mg===null?'':s.suggested_additional_mg/1000);i.step='0.001';i.min='0';i.max=s.remaining_mg/1000;i.dataset.spool=s.spool_id;i.className='uid-extra-amount';if(s.reserved){i.value='0';i.disabled=true}inputs.push([s,i]);return i}
  if(d.manual_spool_selection){
   dialog.append(node('p',text('Исходные катушки неизвестны. Выберите их вручную и укажите только ещё не учтённый расход. Проверьте другие записи этой печати после ошибки и продолжения. Текущие назначения не подставляются.','Original spools are unknown. Choose them and enter only usage not already accounted. Check other records of this print after error/resume. Current assignments are not used.','Ursprüngliche Spulen unbekannt. Spulen wählen und nur noch nicht erfassten Verbrauch eingeben. Andere Einträge nach Fehler/Fortsetzung prüfen.','Початкові котушки невідомі. Виберіть їх і вкажіть лише невраховані витрати. Перевірте інші записи після помилки та продовження.','Bobinas originales desconocidas. Elíjalas e indique solo consumo no contabilizado. Revise otros registros tras error y reanudación.')));
   const label=node('label',text('Катушка','Spool','Spule','Котушка','Bobina')),select=node('select');select.id='uid-history-spool';select.append(new Option('—',''));
   for(const s of d.candidates){const remote=data.spools[s.spool_id]?.spoolman;const option=new Option(s.name+' · '+weight(s.remaining_mg)+(remote?' · Spoolman #'+remote.id:''),s.spool_id);option.disabled=s.reserved;select.append(option)}
   label.append(select);dialog.append(label);
   const add=historyButton(text('Добавить катушку','Add spool','Spule hinzufügen','Додати котушку','Añadir bobina'),()=>{
    const s=d.candidates.find(s=>s.spool_id===select.value);if(!s||s.reserved||inputs.some(([v])=>v.spool_id===s.spool_id))return;
    const i=amount(s);i.parentElement.classList.add('gd-field');note.parentElement.before(i.parentElement);select.selectedOptions[0].disabled=true;select.value='';
   });add.id='uid-history-add-spool';dialog.append(add);
  }else{
   d.candidates.forEach(amount);
   dialog.append(node('p',text('Подставлен дополнительный расход из сохранённого плана за вычетом уже учтённого. Отредактируйте при необходимости. При неизвестной привязке или замене катушек заполните расход вручную.','Additional usage is prefilled from the saved plan minus usage already accounted. Edit if needed. Unknown mappings or spool changes require manual amounts.')));
  }
  const note=field(text('Комментарий (необязательно)','Comment (optional)','Kommentar (optional)','Коментар (необов’язково)','Comentario (opcional)'),'text');note.id='uid-review-note';note.maxLength=2000;
  const ack=field(text('Печать завершилась. Катушки и дополнительный расход проверены.','The print has ended. Spools and additional usage have been verified.','Der Druck ist beendet. Spulen und zusätzlicher Verbrauch wurden geprüft.','Друк завершено. Котушки й додаткові витрати перевірено.','La impresión terminó. Se verificaron las bobinas y el consumo adicional.'),'checkbox');ack.id='uid-review-ack';
  const request=crypto.randomUUID();let submitted=null;
  const linked=d.candidates.some(s=>data.spools[s.spool_id]?.spoolman);
  const apply=historyButton(linked?text('Учесть в Tracker и продолжить','Account in Tracker and continue'):labels.confirm(),async()=>{
   if(!ack.checked||!inputs.length||inputs.some(([s,i])=>i.value===''||!i.validity.valid))throw Error(text('Проверьте значения и подтвердите расход.','Check amounts and confirm usage.','Mengen, Begründung und Bestätigung prüfen.','Перевірте значення, підставу та підтвердження.','Revise cantidades, motivo y confirmación.'));
   const payload={job_key:d.job.job_key,action:'account',expected_revision:d.revision,request_id:request,confirmed:true,completed:true,note:note.value,allocations_mg:Object.fromEntries(inputs.map(([s,i])=>[s.spool_id,Math.round(Number(i.value)*1000)]))};
   const encoded=JSON.stringify(payload);if(submitted&&submitted!==encoded)throw Error(text('Запрос уже отправлен. Повторите без изменений или откройте задание заново.','Request already sent. Retry unchanged or reopen the job.'));
   submitted=encoded;await api('/api/history_decide',payload);await loadData();
   const result=await detail(d.job.job_key);
   if(result.remote_operations.length)await deliveryStep(d.job.job_key,desktopFormData||data);else dialog.close();
  });apply.id='uid-review-apply';actions(primary(apply));dialog.append(node('p',text('Шаг 1: учёт в Tracker. Для связанных катушек следующий шаг в этом окне — отправка в Spoolman.','Step 1: account in Tracker. For linked spools, the next step in this window sends usage to Spoolman.','Bei verknüpften Spoolman-Spulen kommt der Verbrauch in die Warteschlange. Unklare Übertragungen werden nicht automatisch wiederholt.','Для пов’язаної котушки Spoolman витрати потраплять до черги. Невизначена відправка автоматично не повторюється.','Para bobinas de Spoolman, el consumo entra en la cola. Los envíos inciertos nunca se repiten automáticamente.')));
  window.graphiteHistoryDialog?.(dialog);
 }
 async function deliveryStep(key,data,notice=''){
  const state=await desktopCore('state'),d=await detail(key),rows=state.delivery.filter(r=>r.job_key===key);
  view(d,data);dialog.dataset.stage='spoolman';
  const complete=rows.length&&rows.every(r=>r.state==='sent');
  dialog.append(node('h3',complete?text('Шаг 3 · Готово: Tracker и Spoolman','Step 3 · Done: Tracker and Spoolman'):text('Шаг 2 · Отправка в Spoolman','Step 2 · Send to Spoolman')));
  dialog.append(node('p',text('Локально учтено: ','Accounted locally: ')+weight(d.accounted_mg)+'. '+text('Этот расход повторно из Tracker не списывается.','This usage will not be deducted again from Tracker.')));
  const panel=node('div');panel.id='uid-history-delivery-rows';dialog.append(panel);
  const message=node('p',notice);message.id='uid-history-delivery-message';message.setAttribute('role','status');dialog.append(message);
  const ready=rows.filter(r=>['held','pending'].includes(r.state));
  for(const row of rows){
   const card=node('section',undefined,'gd-notice');card.dataset.operation=row.operation_id;
   card.append(node('strong',(data.spools[row.spool_id]?.name||row.spool_id)+' · Spoolman #'+row.remote_id),node('p',row.url),node('p',weight(row.delta_mg)+' · '+deliveryCaption(row.state)));
   panel.append(card);
   if(['held','pending'].includes(row.state)&&state.delivery_enabled&&state.settings.values.spoolman_mode!=='off'){
    try{const checked=await desktopCore('delivery_review',{operation_id:row.operation_id,expected_revision:row.revision});const before=checked.remote.remaining_g;
     card.append(node('p',text('Spoolman: сейчас ','Spoolman: now ')+(before===null?'—':displayGrams(before)+' g')+text(' → после списания ',' → after deduction ')+(before===null?'—':displayGrams(before-row.delta_mg/1000)+' g')));
    }catch(e){card.append(node('p',text('Проверка Spoolman не завершена: ','Spoolman check incomplete: ')+e.message))}
   }
   if(row.state==='uncertain')card.append(node('p',text('Результат прошлой отправки неизвестен. Нужна сверка в разделе Spoolman; повторно не отправляем.','The previous delivery outcome is unknown. Reconcile in Spoolman settings; no automatic retry.')));
  }
  const buttons=[historyButton(text('Закрыть','Close','Schließen','Закрити','Cerrar'),()=>dialog.close())];
  if(ready.length){
   const requests=new Map(ready.map(r=>[r.operation_id,crypto.randomUUID()]));
   const send=primary(historyButton(text('Отправить в Spoolman','Send to Spoolman','An Spoolman senden','Надіслати у Spoolman','Enviar a Spoolman'),async()=>{
    let outcome='';
    for(const row of ready){
     const result=await desktopCore('delivery_confirm_send',{operation_id:row.operation_id,expected_revision:row.revision,request_id:requests.get(row.operation_id),confirmed:true});
     if(result.status!=='sent'){outcome=deliveryCaption(result.status);break;}
    }
    await loadData();await deliveryStep(key,desktopFormData||data,outcome);
   }));send.id='uid-history-send';send.disabled=!state.delivery_enabled||state.settings.values.spoolman_mode!=='send'||state.delivery.some(r=>['uncertain','sending'].includes(r.state));buttons.push(send);
   if(send.disabled)message.textContent=text('Локальный учёт сохранён. Для отправки включите режим отправки Spoolman и завершите сверку неизвестных операций.','Local accounting is saved. Enable Spoolman sending and reconcile unknown operations before delivery.');
  }
  const refresh=historyButton(text('Проверить состояние','Check status'),()=>deliveryStep(key,data));refresh.id='uid-history-delivery-refresh';buttons.push(refresh);
  actions(...buttons);window.graphiteHistoryDialog?.(dialog);if(!dialog.open)dialog.showModal();
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
  rows.forEach((row,i)=>{if(!runs[i])return;if(runs[i].closed_without_deduction){const badge=row.querySelector('.head-status');if(badge)badge.textContent=text('Закрыто без списания','Closed without deduction','Ohne Abbuchung geschlossen','Закрито без списання','Cerrado sin descuento')}const remote=data.saved_history[runs[i].job_key]?.remote_operations||[];if(remote.length&&runs[i].status==='committed'){const badge=row.querySelector('.head-status');if(badge){badge.textContent=text('Учтено в Tracker','Accounted in Tracker')+' · Spoolman: '+(remote.every(r=>r.state==='sent')?text('отправлено','sent'):remote.some(r=>['uncertain','sending'].includes(r.state))?text('нужна сверка','reconcile'):remote.every(r=>r.state==='resolved')?text('без отправки','not sent'):text('ожидает отправки','awaiting delivery'));badge.style.whiteSpace='normal'}}if(row.querySelector('.uid-expand'))return;const b=historyButton(labels.expand(),()=>open(runs[i].job_key,data));b.className='uid-expand uid-history-secondary';row.append(b)});
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
