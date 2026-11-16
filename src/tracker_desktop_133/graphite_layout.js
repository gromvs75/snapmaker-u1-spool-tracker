// The approved layout, using the existing controls and their guarded handlers.
// No accounting calculations, requests or persistence are introduced here.
(()=>{
 const t=desktopText, bindings=[];
 const label=(target,...translations)=>{bindings.push(()=>target.textContent=t(...translations));return target};
 const heading=(id,title,description)=>{const box=node('div',undefined,'graphite-pagehead'),copy=node('div');box.id=id;copy.append(label(node('h2'),...title),label(node('p',undefined,'subtitle'),...description));box.append(copy);return box};
 const chrome=node('header',undefined,'graphite-chrome'),header=document.querySelector('.header-bar'),context=el('desktop-printer-context');
 header.before(chrome);chrome.append(header,context);
 const brand=node('div',undefined,'graphite-brand'),oldBrand=header.querySelector('.brand-text');
 header.prepend(brand);brand.append(header.querySelector('.brand-logo'),node('strong','Spool Tracker'));
 const about=node('details',undefined,'graphite-about');about.append(label(node('summary'),'О приложении','About','Über die App','Про застосунок','Acerca de'),oldBrand);
 document.querySelector('.graphite-footer').append(about);
 const printerLabel=context.querySelector('label');printerLabel.classList.add('graphite-printer-label');
 // Keep the accessible label while replacing its visual text with a printer glyph.
 printerLabel.setAttribute('aria-label',printerLabel.textContent);
 const icon=(path)=>{const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');svg.innerHTML='<path d="'+path+'" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>';return svg};
 const printerIcon=icon('M7 8V3h10v5M7 17H4V9h16v8h-3M7 14h10v7H7zM17 11h.01');context.prepend(printerIcon);
 const sideIcons=['M4 4v16M8 4v16M12 6l5 14M18 4l3 14','M3 8l9-5 9 5-9 5zM3 12l9 5 9-5M3 16l9 5 9-5'];
 const settingsIcons=['M7 8V3h10v5M7 17H4V9h16v8h-3M7 14h10v7H7zM17 11h.01','M4 6c0-4 16-4 16 0s-16 4-16 0v12c0 4 16 4 16 0V6M4 12c0 4 16 4 16 0','M5 2h14v20H5zM8 5h8v4H8zM8 12h.01M12 12h.01M16 12h.01M8 16h.01M12 16h.01M16 16h.01','M3 3h18v5H3zM5 8v13h14V8M10 12h4'];
 bindings.push(()=>{for(const [selector,paths] of [['.inventory-tabs button',sideIcons],['.settings-nav button',settingsIcons]])document.querySelectorAll(selector).forEach((b,i)=>{if(!b.querySelector('svg'))b.prepend(icon(paths[i%paths.length]))})});
 // Library: page action, search tools, then a compact five-column inventory.
 const libraryTitle=el('t-spools-hdr');
 const libraryHead=heading('graphite-library-heading',['Библиотека','Library','Bibliothek','Бібліотека','Biblioteca'],['Остатки, материалы и физические назначения','Balances, materials and physical assignments','Restmengen, Materialien und physische Zuweisungen','Залишки, матеріали й фізичні призначення','Saldos, materiales y asignaciones físicas']);
 libraryTitle.before(libraryHead);libraryTitle.hidden=true;libraryHead.append(el('inventory-create'));
 const inventory=document.querySelector('.spool-inventory');
 inventory.querySelector('colgroup').innerHTML='<col style="width:27%"><col style="width:12%"><col style="width:15%"><col style="width:28%"><col style="width:18%">';
 const assignmentHeader=label(node('th'),'Назначение','Assignment','Zuweisung','Призначення','Asignación');el('t-th-act').before(assignmentHeader);
 const moreLabel=()=>t('Действия с катушкой','Spool actions','Spulenaktionen','Дії з котушкою','Acciones de bobina');
 function library(data){
  for(const row of el('spools-table').rows){
   if(row.dataset.graphiteLayout)continue;row.dataset.graphiteLayout='true';
   const spool=data.spools[row.dataset.spoolId];if(!spool)continue;
   const [name,material,balance,actions]=row.cells;
   const assignments=node('td',undefined,'graphite-assignments');
   const previous=name.querySelector('.uid-inventory-assignments');
   // The complete (possibly multi-printer) identity remains available to search.
   if(previous)previous.remove();assignments.classList.add('uid-inventory-assignments');
   for(const a of spool.assignments||[]){const item=node('div');item.append(node('span',a.printer_name+' · T'+a.channel),node('small',a.state==='recognized'?t('Метка распознана','Tag recognized','Tag erkannt','Мітку розпізнано','Etiqueta reconocida'):a.state==='manual_confirmed'?t('Подтверждено вручную','Confirmed manually','Manuell bestätigt','Підтверджено вручну','Confirmado manualmente'):t('Требует проверки','Needs review','Prüfung erforderlich','Потребує перевірки','Requiere revisión')));assignments.append(item)}
   if(!spool.assignments?.length)assignments.append(node('span',t('Не назначена','Unassigned','Nicht zugewiesen','Не призначена','Sin asignar')));
   row.insertBefore(assignments,actions);
   const exact=balance.querySelector('input'),details=node('details',undefined,'graphite-row-menu'),summary=node('summary','…');summary.setAttribute('aria-label',moreLabel()+' · '+spool.name);details.append(summary);
   const menu=node('div',undefined,'graphite-menu-items');details.append(menu);
   if(exact){const edit=node('label',t('Изменить остаток, г','Edit balance, g','Restmenge ändern, g','Змінити залишок, г','Cambiar saldo, g'));edit.append(exact);menu.append(edit)}
   balance.replaceChildren(node('span',displayGrams(spool.remaining_g)+' '+gramUnit(),'graphite-balance'));
   const params=actions.querySelector('.inventory-param-button');params.textContent=t('Параметры','Parameters','Parameter','Параметри','Parámetros');
   for(const child of [...actions.children])if(child!==params)menu.append(child);
   const color=name.querySelector('.color-picker');if(color){color.querySelector('summary').textContent=t('Цвет','Color','Farbe','Колір','Color');menu.append(color)}
   actions.replaceChildren();const group=node('div',undefined,'graphite-row-actions');group.append(params,details);actions.append(group);
   details.addEventListener('toggle',()=>{if(details.open)for(const other of document.querySelectorAll('.graphite-row-menu[open]'))if(other!==details)other.open=false});
  }
 }
 // Printer form: every moved button keeps its form ownership and listener.
 const form=el('printer-form'),connection=node('section',undefined,'graphite-connection-section'),connectionHeading=node('div',undefined,'graphite-connection-heading');
 connectionHeading.append(label(node('h3'),'Соединение','Connection','Verbindung','З’єднання','Conexión'),el('printer-status'));
 const connectionActions=node('div',undefined,'graphite-connection-actions');connectionActions.append(el('desktop-connections-toggle'),el('heads-read'));
 connection.append(connectionHeading,el('desktop-connections-message'),el('printer-test-result'),connectionActions,el('heads-content'));form.append(connection);
 const address=el('printer-host').parentElement;
 for(const [id,words] of [['printer-host',['Адрес Moonraker','Moonraker address','Moonraker-Adresse','Адреса Moonraker','Dirección Moonraker']],['printer-port',['Порт','Port','Port','Порт','Puerto']]]){const input=el(id),field=node('label');field.append(label(node('span'),...words),input);address.append(field)}
 bindings.push(()=>{el('printer-title').textContent=t('Принтер','Printer','Drucker','Принтер','Impresora');el('printer-help').textContent=t('Параметры выбранного U1 и состояние соединения','Selected U1 settings and connection status','Einstellungen des gewählten U1 und Verbindungsstatus','Параметри вибраного U1 та стан з’єднання','Ajustes del U1 seleccionado y estado de conexión')});
 const overviewHead=heading('graphite-overview-heading',['Обзор','Overview','Übersicht','Огляд','Resumen'],['','','','','']);el('view-overview').prepend(overviewHead);
 const headsTitle=node('div',undefined,'graphite-heads-heading'),assign=node('button');assign.type='button';label(assign,'Назначения →','Assignments →','Zuweisungen →','Призначення →','Asignaciones →');assign.onclick=()=>{el('nav-spools').click();document.querySelector('[data-inventory-tab=slots]').click()};headsTitle.append(label(node('h3'),'Головки и катушки','Toolheads and spools','Druckköpfe und Spulen','Голівки й котушки','Cabezales y bobinas'),assign);el('sidebar-slots').before(headsTitle);
 bindings.push(()=>{overviewHead.querySelector('p').textContent=desktopFormData?.printers?.find(p=>p.id===desktopFormData.selected_printer)?.name||''});
 const historyHead=heading('graphite-history-heading',['История','History','Verlauf','Історія','Historial'],['Сохранённые планы, учтённый расход и задания для проверки','Saved plans, accounted usage and jobs to review','Gespeicherte Pläne, erfasster Verbrauch und zu prüfende Aufträge','Збережені плани, враховані витрати й завдання для перевірки','Planes guardados, consumo contabilizado y trabajos para revisar']);el('view-history').prepend(historyHead);
 const baseHistory=renderHistory;
 renderHistory=(data,force=false)=>{
  baseHistory(data,force);
  const root=el('history-content'),list=root.querySelector('details');if(!list||list.dataset.graphiteLayout)return;list.dataset.graphiteLayout='true';list.open=true;list.classList.add('graphite-history-list');
  const detail=node('details',undefined,'graphite-history-explanation');detail.append(node('summary',t('Об истории учёта','About accounting history','Über den Verbrauchsverlauf','Про історію обліку','Sobre el historial de consumo')));
  for(const child of [...list.children])if(child.matches('summary,p.subtitle')){if(child.matches('summary'))child.hidden=true;detail.append(child)}
  const columns=node('div',undefined,'graphite-history-columns');for(const words of [['Задание','Job','Auftrag','Завдання','Trabajo'],['Состояние','State','Status','Стан','Estado'],['Учтено','Accounted','Erfasst','Враховано','Contabilizado'],['','','','','']])columns.append(node('span',t(...words)));const listSummary=node('summary');listSummary.hidden=true;list.prepend(listSummary,columns);
  const runs=Object.values(data.runs||{}).sort((a,b)=>b.start_time-a.start_time).slice(0,20);
  [...list.querySelectorAll('.history-row')].forEach((row,i)=>{
   const run=runs[i];if(!run)return;
   const name=row.querySelector('.history-name'),date=row.querySelector('.history-date'),usage=row.querySelector('.history-usage'),badge=row.querySelector('.head-status'),open=row.querySelector('.uid-expand');
   const job=node('span',undefined,'graphite-history-job'),actions=node('span',undefined,'graphite-history-actions');
   const printer=data.printers?.find(p=>p.id===(data.saved_history[run.job_key]?.job.printer_id||data.selected_printer));if(printer)date.append(document.createTextNode(' · '+printer.name));job.append(name,date);
   usage.title=usage.textContent;usage.textContent=run.status==='active'&&!run.accounted_g?'—':displayGrams(run.accounted_g||0)+' '+gramUnit();
   if(!run.closed_without_deduction)badge.textContent=run.status==='active'?t('Печатается','Printing','Druck läuft','Друкується','Imprimiendo'):run.status==='committed'?t('Учтено','Accounted','Erfasst','Враховано','Contabilizado'):t('Нужна проверка','Needs review','Prüfung erforderlich','Потрібна перевірка','Requiere revisión');
   badge.dataset.state=run.closed_without_deduction?'closed':run.status;
   open.textContent=run.status==='review'&&!run.closed_without_deduction?t('Проверить','Review','Prüfen','Перевірити','Revisar'):t('Открыть','Open','Öffnen','Відкрити','Abrir');actions.append(open);
   for(const other of [...row.children])if(![name,date,usage,badge].includes(other))actions.append(other);
   row.replaceChildren(job,badge,usage,actions);
  });list.after(detail);
 };
 const loaded=window.desktopInventoryLoaded;
 window.desktopInventoryLoaded=data=>{loaded(data);library(data);for(const update of bindings)update()};
 bindings.push(()=>{
  el('inventory-create').textContent='＋ '+t('Добавить','Add','Hinzufügen','Додати','Añadir');
  el('inventory-search').placeholder=t('Название, материал или UID','Name, material or UID','Name, Material oder UID','Назва, матеріал або UID','Nombre, material o UID');
  el('printer-save').textContent=t('Сохранить настройки','Save settings','Einstellungen speichern','Зберегти налаштування','Guardar ajustes');
  document.querySelector('.graphite-footer>span').textContent=t('Локальный учёт · SQLite','Local accounting · SQLite','Lokale Erfassung · SQLite','Локальний облік · SQLite','Contabilidad local · SQLite');
 });
 const localize=()=>{for(const update of bindings)update()};new MutationObserver(localize).observe(el('nav-settings'),{childList:true});localize();
 document.addEventListener('click',event=>{for(const menu of document.querySelectorAll('.graphite-row-menu[open]'))if(!menu.contains(event.target))menu.open=false});
 document.addEventListener('keydown',event=>{if(event.key==='Escape')for(const menu of document.querySelectorAll('.graphite-row-menu[open]')){menu.open=false;menu.querySelector('summary').focus()}});
})();
