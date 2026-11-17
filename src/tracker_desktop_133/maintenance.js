// Parameters, archive, ledger statistics and versioned backups in the full shell.
(()=>{
 const t=desktopText, $=el;
 const style=node('style');style.textContent='#desktop-backup-dialog{line-height:1.5}#desktop-backup-dialog>label{display:flex;align-items:flex-start;gap:10px;margin:18px 0}#desktop-backup-dialog input[type=checkbox]{flex:0 0 auto;width:18px!important;height:18px;min-height:18px;margin:3px 0 0;padding:0}#desktop-backup-dialog>button{margin:6px 12px 6px 0}#desktop-backup-dialog button:disabled{opacity:.45;cursor:not-allowed}#desktop-statistics{margin-bottom:18px}#desktop-statistics summary{cursor:pointer;font-weight:650}#desktop-statistics td{padding:8px 12px}#desktop-statistics td:last-child{text-align:right}#inventory-toolbar>label{display:flex;align-items:center;gap:8px}#inventory-toolbar>label input{margin:0;width:18px!important;height:18px;min-height:18px;padding:0}.desktop-archive-action{margin-top:8px;background:#253147}';document.head.append(style);
 const labels={
  archive:()=>t('Архив','Archive','Archiv','Архів','Archivo'),
  put:()=>t('В архив','Archive spool','Archivieren','До архіву','Archivar bobina'),
  take:()=>t('Вернуть в библиотеку','Restore to library','Zur Bibliothek','Повернути до бібліотеки','Volver a la biblioteca'),
  stats:()=>t('Статистика учёта','Accounting statistics','Verbrauchsstatistik','Статистика обліку','Estadísticas de consumo'),
  check:()=>t('Проверить копию','Validate backup','Sicherung prüfen','Перевірити копію','Validar copia'),
  restore:()=>t('Восстановить проверенную копию','Restore validated backup','Geprüfte Sicherung wiederherstellen','Відновити перевірену копію','Restaurar copia validada'),
  close:()=>t('Закрыть','Close','Schließen','Закрити','Cerrar')
 };
 const button=(id,caption,action)=>{const b=node('button',caption);b.id=id;b.type='button';b.onclick=()=>act(action);return b};
 const archiveLabel=node('label'),archive=node('input'),archiveCaption=node('span');archive.type='checkbox';archive.id='desktop-archive-view';archive.style.width='auto';archiveLabel.append(archive,archiveCaption);$('inventory-toolbar').append(archiveLabel);
 archive.onchange=()=>$('inventory-search').dispatchEvent(new Event('input'));
 const loaded=window.desktopInventoryLoaded;
 window.desktopInventoryLoaded=data=>{
  loaded(data);
  for(const row of $('spools-table').children){
   const sid=row.dataset.spoolId,s=data.spools[sid];if(!s)continue;
   row.dataset.archived=String(Boolean(s.archived));
   const b=button('',s.archived?labels.take():labels.put(),async()=>{
    if(!await window.graphiteConfirm((s.archived?labels.take():labels.put())+' — '+s.name+'?'))return;
    await api('/api/spools/archive',{id:sid,archived:!s.archived});await loadData();
   });b.className='desktop-archive-action';row.lastElementChild.append(b);
  }
  $('inventory-search').dispatchEvent(new Event('input'));
  localize();updateBackupAvailability();
  if(stats.open)void refreshStats();
 };
 $('cal-form').addEventListener('submit',event=>{
  event.preventDefault();event.stopImmediatePropagation();act(async()=>{
   const value=id=>$(id).value.trim()===''?null:$(id).value;
   await api('/api/spools/calibration',{id:$('cal-spool').value,calibration:{diameter_mm:value('cal-diameter'),density_g_cm3:value('cal-density')}});
   await loadData();window.inventoryParametersSaved?.();
  });
 },true);
 const stats=node('details','', 'card');stats.id='desktop-statistics';
 const statsTitle=node('summary'),statsBody=node('div');statsBody.id='desktop-statistics-body';stats.append(statsTitle,statsBody);$('view-history').prepend(stats);
 let statsRequest=0;
 async function refreshStats(){
  const request=++statsRequest;
  try{
   const data=await api('/api/statistics');
   if(request!==statsRequest||data.printer_id!==desktopFormData?.selected_printer)return;
   const moreOpen=!!statsBody.querySelector('.gd-stat-more[open]');statsBody.replaceChildren();
   const printer=desktopFormData.printers.find(p=>p.id===data.printer_id);
   statsBody.append(node('h3',printer?.name||data.printer_id),node('p',t('Уже списано локально: ','Already deducted locally: ','Lokal abgebucht: ','Вже списано локально: ','Ya descontado localmente: ')+displayGrams(data.total_mg/1000)+' '+gramUnit()));
   statsBody.append(node('p',t('Включает частичный учёт и отменённые задания. Очередь Spoolman не прибавляется повторно.','Includes partial and cancelled jobs. Spoolman delivery is not counted again.','Enthält Teilverbrauch und abgebrochene Aufträge. Spoolman wird nicht erneut gezählt.','Включає частковий облік і скасовані завдання. Черга Spoolman не додається повторно.','Incluye trabajos parciales y cancelados. Spoolman no se cuenta de nuevo.')));
   const status={active:t('Печатается','Printing','Druck läuft','Друкується','Imprimiendo'),review:t('Требует проверки','Needs review','Prüfung erforderlich','Потребує перевірки','Requiere revisión'),completed:t('Учтено','Accounted','Erfasst','Враховано','Contabilizado'),cancelled:t('Отменено','Cancelled','Abgebrochen','Скасовано','Cancelado'),resolved:t('Закрыто','Closed','Geschlossen','Закрито','Cerrado')};
   statsBody.append(node('p',Object.entries(data.counts).map(([k,v])=>(status[k]||k)+': '+v).join(' · ')));
   const primary=node('div',undefined,'gd-stat-grid'),more=node('details',undefined,'gd-stat-more'),secondary=node('div',undefined,'gd-stat-grid');more.open=moreOpen;more.append(node('summary',t('Основание учёта и месяцы','Accounting basis and months','Buchungsgrundlage und Monate','Підстава обліку та місяці','Base del cómputo y meses')),secondary);statsBody.append(primary,more);let tableCount=0;
   function table(title,rows){const section=node('section');section.append(node('h3',title));const table=node('table');for(const [name,amount] of rows){const row=node('tr');row.append(node('td',name),node('td',displayGrams(amount/1000)+' '+gramUnit()));table.append(row)}section.append(table);(tableCount++<2?primary:secondary).append(section)}
   table(t('По катушкам','By spool','Nach Spule','За котушками','Por bobina'),Object.entries(data.by_spool).map(([sid,n])=>[data.spool_names[sid]||sid,n]));
   table(t('По головкам','By toolhead','Nach Druckkopf','За голівками','Por cabezal'),[...data.head_mg.map((n,i)=>['T'+i,n]),[t('Без доказанной головки','Head not established','Druckkopf nicht belegt','Голівку не підтверджено','Cabezal sin confirmar'),data.unattributed_mg]]);
   const methods={legacy_import:t('Перенесено из 1.x','Imported from 1.x','Aus 1.x übernommen','Перенесено з 1.x','Importado de 1.x'),motion_estimate:t('Оценка по движению','Motion estimate','Bewegungsschätzung','Оцінка за рухом','Estimación por movimiento'),executed_gcode:t('Выполненный G-code','Executed G-code','Ausgeführter G-Code','Виконаний G-code','G-code ejecutado'),completed_gcode:t('Завершённый план','Completed plan','Abgeschlossener Plan','Завершений план','Plan completado'),calculated_history:t('Расчёт по истории','History estimate','Historienberechnung','Розрахунок за історією','Estimación por historial'),manual_reconciliation:t('Ручное подтверждение','Manual confirmation','Manuelle Bestätigung','Ручне підтвердження','Confirmación manual')};
   table(t('Основание учёта','Accounting basis','Buchungsgrundlage','Підстава обліку','Base del cómputo'),Object.entries(data.by_basis).map(([basis,n])=>[methods[basis]||t('Неизвестно','Unknown','Unbekannt','Невідомо','Desconocido'),n]));
   table(t('По месяцам (UTC)','By month (UTC)','Nach Monat (UTC)','За місяцями (UTC)','Por mes (UTC)'),Object.entries(data.by_month).sort());
   if(data.legacy_records)statsBody.append(node('p',t('Старые записи без журнала дебетов не включены: ','Legacy records without a debit ledger excluded: ','Altdaten ohne Buchungsjournal ausgeschlossen: ','Старі записи без журналу списань не включено: ','Registros antiguos sin libro de cargos excluidos: ')+data.legacy_records));
  }catch(e){if(request===statsRequest)statsBody.textContent=String(e.message||e)}
 }
 stats.ontoggle=()=>{if(stats.open)void refreshStats()};
 const dialog=node('dialog');dialog.id='desktop-backup-dialog';dialog.className='inventory-dialog';document.body.append(dialog);
 const close=button('desktop-backup-close',labels.close(),()=>dialog.close()),info=node('p'),preview=node('div'),file=node('input');preview.id='desktop-backup-preview';preview.setAttribute('role','status');file.id='desktop-backup-file';file.type='file';file.accept='.json';file.hidden=true;
 const fileName=node('span'),choose=button('desktop-backup-choose','',()=>file.click());
 const ackLabel=node('label'),ack=node('input'),ackText=node('span');ack.type='checkbox';ack.id='desktop-backup-ack';ack.style.width='auto';ackLabel.append(ack,ackText);
 let packageData=null,checked=null,restoreBusy=false;
 function reset(){packageData=null;checked=null;ack.checked=false;preview.textContent='';apply.disabled=true}
 const check=button('desktop-backup-check',labels.check(),async()=>{
  const candidate=packageData;checked=null;ack.checked=false;apply.disabled=true;
  if(!candidate)throw Error(t('Выберите копию.','Select a backup.','Sicherung wählen.','Виберіть копію.','Seleccione una copia.'));
  let result;try{result=await desktopCore('validate_backup',{package:candidate})}catch(e){preview.textContent=e.message;preview.dataset.error='true';return}
  delete preview.dataset.error;
  if(packageData!==candidate)return;
  checked=result;preview.replaceChildren(node('strong',t('Целостность проверена','Integrity verified','Integrität geprüft','Цілісність перевірено','Integridad verificada')));
  const counts=node('dl',undefined,'gd-backup-counts');
  for(const [value,words] of [[result.spools,['Катушки','Spools','Spulen','Котушки','Bobinas']],[result.jobs,['Задания','Jobs','Aufträge','Завдання','Trabajos']],[result.debits,['Списания','Debits','Abbuchungen','Списання','Cargos']],[result.remote_operations,['Операции Spoolman','Spoolman operations','Spoolman-Vorgänge','Операції Spoolman','Operaciones Spoolman']]]){const pair=node('div');pair.append(node('dt',t(...words)),node('dd',String(value)));counts.append(pair)}preview.append(counts);
  if(result.source_format==='legacy')preview.append(node('p',t(
   'Копия 1.x → 2.0. Настройки, катушки, планы и история будут перенесены. Остатки сохранятся без новых списаний. Подключения и отправка Spoolman останутся выключены; назначения и старые незавершённые отправки требуют проверки.',
   '1.x backup → 2.0. Settings, spools, plans and history will be imported. Balances are preserved without new deductions. Connections and Spoolman sending stay off; assignments and unfinished sends require review.',
   'Sicherung 1.x → 2.0. Einstellungen, Spulen, Pläne und Verlauf werden übernommen. Restmengen bleiben ohne neue Abbuchungen erhalten. Verbindungen und Spoolman-Versand bleiben aus; Zuweisungen und offene Sendungen müssen geprüft werden.',
   'Копія 1.x → 2.0. Налаштування, котушки, плани та історію буде перенесено. Залишки збережуться без нових списань. Підключення й відправлення Spoolman залишаться вимкненими; призначення та незавершені відправлення потребують перевірки.',
   'Copia 1.x → 2.0. Se importarán ajustes, bobinas, planes e historial. Los saldos se conservan sin nuevos descuentos. Las conexiones y envíos Spoolman quedan desactivados; revise las asignaciones y los envíos pendientes.')));
 });
 const apply=button('desktop-backup-apply',labels.restore(),async()=>{
  if(restoreBusy||!checked||!ack.checked)return;
  restoreBusy=true;apply.disabled=true;
  try{
   const result=await desktopCore('restore_backup',{package:packageData,expected_revision:checked.current_revision,confirmed:true});
   reset();dialog.close();sessionStorage.clear();desktopSpoolmanData=null;desktopFormData=null;
   await loadData();$('backup-availability').textContent=(extra[currentLang]||extra.en).importDone+' '+result.rollback_file;
  }finally{restoreBusy=false;checked=null;ack.checked=false;apply.disabled=true}
 });
 ack.onchange=()=>apply.disabled=!checked||!ack.checked||restoreBusy;
 file.onchange=()=>act(async()=>{reset();const f=file.files[0];fileName.textContent=f?.name||'';if(!f)return;if(f.size>46*1024*1024)throw Error('Maximum 46 MB');packageData=JSON.parse(await f.text())});
 dialog.append(close,node('h2'),info,file,choose,fileName,node('br'),check,preview,ackLabel,apply);
 updateBackupAvailability=function(){
  $('backup-export').disabled=backupBusy;$('backup-import').disabled=backupBusy;
  $('backup-availability').textContent='';
 };
 $('backup-export').addEventListener('click',event=>{
  event.stopImmediatePropagation();act(()=>withBackupDialog(async()=>{
   if(desktopFormData?.native_backup){const result=await api('/api/backup_file',{action:'export'});if(result.status==='ok')alert((extra[currentLang]||extra.en).exportDone+'\n'+result.path)}
   else{const value=await desktopCore('backup_package',{}),url=URL.createObjectURL(new Blob([JSON.stringify(value)],{type:'application/json'}));const link=node('a');link.href=url;link.download='tracker-2.0-backup.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),10000)}
  }));
 },true);
 $('backup-import').addEventListener('click',event=>{
  event.stopImmediatePropagation();act(()=>withBackupDialog(async()=>{
   reset();file.value='';fileName.textContent='';localize();
   if(desktopFormData?.native_backup){const result=await api('/api/backup_file',{action:'select'});if(result.status!=='ok')return;packageData=result.package;choose.hidden=true}else choose.hidden=false;
   dialog.showModal();
  }));
 },true);
 function localize(){
  choose.textContent=t('Выбрать файл','Choose file','Datei wählen','Вибрати файл','Elegir archivo');
  archiveCaption.textContent=labels.archive();statsTitle.textContent=labels.stats();close.textContent=labels.close();check.textContent=labels.check();apply.textContent=labels.restore();dialog.querySelector('h2').textContent=(extra[currentLang]||extra.en).backupTitle;
  info.textContent=t('Остановите подключения. После восстановления назначения требуют проверки, старые отправки Spoolman — ручной сверки. Перед заменой будет сохранена копия текущей базы.','Stop connections. After restore, assignments require review and old Spoolman deliveries require manual reconciliation. The current database is backed up before replacement.','Verbindungen stoppen. Nach Wiederherstellung Zuweisungen und alte Spoolman-Vorgänge prüfen. Die aktuelle Datenbank wird vorher gesichert.','Зупиніть підключення. Після відновлення перевірте призначення та старі відправки Spoolman. Поточну базу буде збережено перед заміною.','Detenga las conexiones. Tras restaurar, revise las asignaciones y concilie los envíos anteriores de Spoolman. Se guardará la base actual antes de reemplazarla.');
  ackText.textContent=t('Подтверждаю замену базы проверенной копией','Replace the database with the validated backup','Datenbank durch geprüfte Sicherung ersetzen','Підтверджую заміну бази перевіреною копією','Reemplazar la base con la copia validada');
  $('cal-title').textContent=t('Параметры катушки','Spool parameters','Spulenparameter','Параметри котушки','Parámetros de bobina');
  $('cal-help').textContent=t('Диаметр и плотность используются для оценки массы будущих заданий. Сохранённые планы и списания не пересчитываются. UID назначается только через регистрацию метки.','Diameter and density estimate mass for future jobs. Saved plans and debits are not recalculated. UID is assigned only through tag registration.','Durchmesser und Dichte gelten für künftige Aufträge. Gespeicherte Pläne und Abbuchungen bleiben unverändert. UID nur über Tag-Registrierung.','Діаметр і густина — для оцінки майбутніх завдань. Збережені плани й списання не перераховуються. UID — лише через реєстрацію мітки.','Diámetro y densidad para trabajos futuros. Los planes y cargos guardados no se recalculan. UID solo mediante registro de etiqueta.');
  $('cal-diameter').placeholder=t('Диаметр, мм','Diameter, mm','Durchmesser, mm','Діаметр, мм','Diámetro, mm');$('cal-density').placeholder=t('Плотность, г/см³','Density, g/cm³','Dichte, g/cm³','Густина, г/см³','Densidad, g/cm³');$('cal-save').textContent=t('Сохранить параметры','Save parameters','Parameter speichern','Зберегти параметри','Guardar parámetros');
 }
 new MutationObserver(localize).observe($('nav-spools'),{childList:true});localize();updateBackupAvailability();
})();
