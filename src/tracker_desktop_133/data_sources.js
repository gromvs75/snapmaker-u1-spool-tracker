// Independent read-only diagnostics. Expand/collapse survives telemetry refresh.
(()=>{
 const t=desktopText,section=node('section',undefined,'dash-sources');section.id='dashboard-sources';
 const title=node('h3');section.append(title);const grid=node('div',undefined,'dash-source-grid');section.append(grid);
 document.querySelector('#view-overview .sidebar').before(section);
 const paths=['M9 3v5m6-5v5M6 8h12v4a6 6 0 0 1-6 6v4m0-4a6 6 0 0 1-6-6V8',
  'M6 3h12v10H6zM9 13v5l3 3 3-3v-5M9 6h6',
  'M3 8a14 14 0 0 1 18 0M6 12a9 9 0 0 1 12 0M9 16a4 4 0 0 1 6 0M12 20h.01',
  'M4 6c0-5 16-5 16 0s-16 5-16 0v12c0 5 16 5 16 0V6M4 12c0 5 16 5 16 0'];
 const rows=paths.map((path,i)=>{
  const details=node('details',undefined,'dash-source'),summary=node('summary'),icon=document.createElementNS('http://www.w3.org/2000/svg','svg');
  icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('aria-hidden','true');icon.innerHTML=`<path d="${path}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>`;
  const copy=node('span',undefined,'dash-source-copy'),heading=node('strong'),badge=node('span',undefined,'dash-source-badge'),short=node('span',undefined,'dash-source-short'),body=node('p');
  details.dataset.source=['connection','head','rfid','spoolman'][i];copy.append(heading,badge,short);summary.append(icon,copy);details.append(summary,body);grid.append(details);
  return {details,heading,badge,short,body};
 });
 const set=(i,name,state,short,body,tone='neutral')=>{const r=rows[i];r.heading.textContent=name;r.badge.textContent=state;r.badge.dataset.tone=tone;r.short.textContent=short;r.body.textContent=body};
 const unknown=()=>t('неизвестно','unknown','unbekannt','невідомо','desconocido');
 function update(data){
  title.textContent=t('Источники данных','Data sources','Datenquellen','Джерела даних','Fuentes de datos');
  const m=data.monitor||{},age=Date.now()/1000-m.checked_at,live=m.connected&&age>=-5&&age<5;
  set(0,t('Соединение','Connection','Verbindung','З’єднання','Conexión'),live?t('есть связь','connected','verbunden','є зв’язок','conectado'):m.state==='disabled'?t('остановлено','stopped','gestoppt','зупинено','detenido'):t('нет связи','offline','offline','немає зв’язку','sin conexión'),
   live?t('Данные принтера получены','Printer data received','Druckerdaten empfangen','Дані принтера отримані','Datos de impresora recibidos'):t('Нет актуальных данных принтера','No current printer data','Keine aktuellen Druckerdaten','Немає актуальних даних принтера','Sin datos actuales de la impresora'),
   t('Соединение с Moonraker. Оно не подтверждает чтение RFID или отправку расхода в Spoolman.','Moonraker connection. This does not confirm RFID reading or usage delivery to Spoolman.','Moonraker-Verbindung. Sie bestätigt weder RFID-Lesung noch Verbrauchsübertragung an Spoolman.','З’єднання з Moonraker. Воно не підтверджує читання RFID або передачу витрат до Spoolman.','Conexión Moonraker. No confirma lectura RFID ni envío de consumo a Spoolman.'),live?'ok':'neutral');
  const printing=['printing','paused'].includes(m.state),head=live&&printing&&Number.isInteger(m.active_head)&&m.active_head>=0&&m.active_head<=3?m.active_head:null;
  set(1,t('Активная головка','Active toolhead','Aktiver Druckkopf','Активна голівка','Cabezal activo'),head===null?unknown():'T'+head,
   head===null?t('Не определена для печати','Not determined for a print','Für Druck nicht bestimmt','Не визначена для друку','Sin determinar para impresión'):m.state==='paused'?t('Выбрана · печать на паузе','Selected · print paused','Ausgewählt · Druck pausiert','Вибрана · друк на паузі','Seleccionado · impresión en pausa'):t('Выбрана принтером','Selected by printer','Vom Drucker ausgewählt','Вибрана принтером','Seleccionado por impresora'),
   t('Физическая головка по текущим данным принтера. Не выводится из цвета катушки или плана нарезки.','Physical toolhead reported by the printer. Not inferred from spool color or the slicing plan.','Physischer Druckkopf laut Drucker. Nicht aus Spulenfarbe oder Slicing-Plan abgeleitet.','Фізична голівка за даними принтера, не за кольором котушки чи планом нарізки.','Cabezal físico según la impresora, no según el color o plan de laminado.'),head===null?'neutral':'ok');
  const reader=data.uid_channels?.[data.selected_printer]||{},channels=Object.values(reader.channels||{}),read=channels.filter(c=>c.state==='present').length,
   faults=channels.filter(c=>['unreadable','stale','conflict'].includes(c.state)).length,ready=live&&reader.state==='ready';
  set(2,'RFID / UID',!live?unknown():reader.state==='module_missing'?t('нет модуля','no module','kein Modul','немає модуля','sin módulo'):ready?faults?t('нужна проверка','needs review','Prüfung nötig','потрібна перевірка','requiere revisión'):t('готов','ready','bereit','готовий','listo'):t('недоступен','unavailable','nicht verfügbar','недоступний','no disponible'),
   ready?t('Читаются метки: ','Tags read: ','Gelesene Tags: ','Читаються мітки: ','Etiquetas leídas: ')+read+' / 4':t('Чтение меток не подтверждено','Tag reading unconfirmed','Tag-Lesung unbestätigt','Читання міток не підтверджено','Lectura de etiquetas sin confirmar'),
   t('Состояние меток показано на карточках катушек ниже. Без модуля доступно ручное назначение.','Tag status appears on the spool cards below. Manual assignment works without the module.','Der Tag-Status steht auf den Spulenkarten unten. Manuelle Zuordnung funktioniert ohne Modul.','Стани міток показані нижче на картках котушок. Без модуля доступне ручне призначення.','El estado de las etiquetas se muestra en las tarjetas de bobina. La asignación manual funciona sin módulo.'),ready&&!faults?'ok':faults?'warning':'neutral');
  const sm=data.data_sources?.spoolman||{},label={unconfigured:t('не настроен','not configured','nicht eingerichtet','не налаштовано','sin configurar'),disabled:t('отключён','disabled','deaktiviert','вимкнено','desactivado'),unchecked:t('не проверен','not checked','nicht geprüft','не перевірено','sin comprobar'),unavailable:t('ошибка чтения','read failed','Lesefehler','помилка читання','error de lectura'),stale:t('данные устарели','stale data','Daten veraltet','дані застаріли','datos obsoletos'),current:t('каталог получен','catalog received','Katalog empfangen','каталог отримано','catálogo recibido')}[sm.state]||unknown();
  const when=sm.checked_at?new Date(sm.checked_at*1000).toLocaleTimeString():null;
  set(3,'Spoolman',label,t('Привязано: ','Linked: ','Verknüpft: ','Прив’язано: ','Vinculadas: ')+(sm.linked||0)+(sm.pending?' · '+t('в очереди: ','pending: ','ausstehend: ','у черзі: ','pendientes: ')+sm.pending:''),
   (when?t('Последняя проверка: ','Last checked: ','Zuletzt geprüft: ','Остання перевірка: ','Última comprobación: ')+when+'. ':'')+t('Статус относится к чтению каталога. Привязка катушки и успешное списание — отдельные состояния. Подробности отправки находятся в настройках Spoolman.','Status refers to catalog reading. Spool linkage and successful usage delivery are separate states. Delivery details are in Spoolman settings.','Status betrifft das Lesen des Katalogs. Spulenverknüpfung und Verbrauchsübertragung sind getrennte Zustände. Details in Spoolman-Einstellungen.','Статус стосується читання каталогу. Прив’язка та списання — окремі стани. Деталі передачі в налаштуваннях Spoolman.','Estado de lectura del catálogo. Vinculación y envío del consumo son estados separados. Detalles en ajustes de Spoolman.'),sm.state==='current'?'ok':['stale','unavailable'].includes(sm.state)?'warning':'neutral');
 }
 const overview=renderOverview;renderOverview=data=>{overview(data);update(data)};
})();
