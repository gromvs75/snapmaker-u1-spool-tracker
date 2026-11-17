// Channel capability is independent of the number of tags awaiting registration.
(()=>{
 const t=desktopText,summary=node('p'),channels=node('p');
 summary.id='desktop-uid-status';summary.setAttribute('role','status');
 channels.id='desktop-uid-channels';channels.className='subtitle';
 el('desktop-tags-dialog').querySelector('.gd-body').prepend(summary,channels);
 const label=state=>({
  ready:t('RFID / UID: канал готов','RFID / UID: channel ready','RFID / UID: Kanal bereit','RFID / UID: канал готовий','RFID / UID: canal listo'),
  module_missing:t('RFID / UID: модуль не установлен. Доступно ручное назначение катушек.','RFID / UID: module not installed. Manual spool assignment is available.','RFID / UID: Modul nicht installiert. Manuelle Spulenzuordnung ist verfügbar.','RFID / UID: модуль не встановлено. Доступне ручне призначення котушок.','RFID / UID: módulo no instalado. Puede asignar bobinas manualmente.'),
  module_unavailable:t('RFID / UID: модуль найден, считыватель не готов','RFID / UID: module found, reader not ready','RFID / UID: Modul gefunden, Leser nicht bereit','RFID / UID: модуль знайдено, зчитувач не готовий','RFID / UID: módulo encontrado, lector no listo'),
  invalid_data:t('RFID / UID: несовместимые или некорректные данные модуля','RFID / UID: incompatible or invalid module data','RFID / UID: inkompatible oder ungültige Moduldaten','RFID / UID: несумісні або некоректні дані модуля','RFID / UID: datos del módulo incompatibles o incorrectos'),
  connecting:t('RFID / UID: проверяем канал…','RFID / UID: checking channel…','RFID / UID: Kanal wird geprüft…','RFID / UID: перевіряємо канал…','RFID / UID: comprobando canal…'),
  stopped:t('RFID / UID: подключения остановлены','RFID / UID: connections stopped','RFID / UID: Verbindungen gestoppt','RFID / UID: підключення зупинені','RFID / UID: conexiones detenidas'),
 }[state]||t('RFID / UID: нет связи','RFID / UID: offline','RFID / UID: offline','RFID / UID: немає зв’язку','RFID / UID: sin conexión'));
 const channelLabel=state=>({
  present:t('метка читается','tag read','Tag gelesen','мітка читається','etiqueta leída'),
  absent:t('метки нет','no tag','kein Tag','мітки немає','sin etiqueta'),
  unreadable:t('метка не читается','tag unreadable','Tag nicht lesbar','мітка не читається','etiqueta ilegible'),
  stale:t('чтение устарело','reading stale','Lesung veraltet','читання застаріло','lectura obsoleta'),
  conflict:t('конфликт меток','tag conflict','Tag-Konflikt','конфлікт міток','conflicto de etiquetas'),
 }[state]||t('ещё не проверено','not checked yet','noch nicht geprüft','ще не перевірено','aún sin comprobar'));
 const base=window.desktopInventoryLoaded;
 window.desktopInventoryLoaded=data=>{
  base(data);
  const channel=data.uid_channels?.[data.selected_printer]||{state:'stopped',channels:{}};
  const printer=data.printers.find(p=>p.id===data.selected_printer);
  summary.textContent=(printer?printer.name+' · ':'')+label(channel.state);
  channels.textContent=channel.state==='ready'?Object.entries(channel.channels).map(([head,c])=>'T'+head+': '+channelLabel(c.state)).join(' · '):'';
  const open=el('desktop-tags-open'),count=data.observations.filter(r=>r.uid&&!r.spool).length;
  open.textContent='RFID / UID · '+(channel.state==='ready'?count:channel.state==='module_missing'?t('нет модуля','no module','kein Modul','немає модуля','sin módulo'):t('недоступен','unavailable','nicht verfügbar','недоступний','no disponible'));
  open.title=summary.textContent;
 };
})();
