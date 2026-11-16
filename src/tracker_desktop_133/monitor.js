// A live Moonraker status is independent of UID readiness and debit permission.
(()=>{
 const t=desktopText;
 const label=s=>({
  printing:t('Печать идёт','Printing','Druck läuft','Друк триває','Imprimiendo'),
  paused:t('Пауза','Paused','Pausiert','Пауза','En pausa'),
  standby:t('Ожидание','Standby','Bereit','Очікування','En espera'),
  complete:t('Печать завершена','Print complete','Druck abgeschlossen','Друк завершено','Impresión finalizada'),
  cancelled:t('Печать отменена','Print cancelled','Druck abgebrochen','Друк скасовано','Impresión cancelada'),
  error:t('Ошибка печати','Print error','Druckfehler','Помилка друку','Error de impresión'),
  disabled:t('Подключения остановлены','Connections stopped','Verbindungen gestoppt','Підключення зупинені','Conexiones detenidas'),
  disconnected:t('Нет связи с принтером','Printer offline','Drucker offline','Немає зв’язку з принтером','Impresora sin conexión'),
 }[s]||t('Состояние печати неизвестно','Print state unknown','Druckstatus unbekannt','Стан друку невідомий','Estado de impresión desconocido'));
 const baseMonitor=updateMonitor,baseOverview=renderOverview;
 updateMonitor=data=>{
  baseMonitor(data);const m=data.monitor;
  el('printer-status').textContent=label(m.state)+(m.connected&&m.filename?' · '+m.filename:'');
  window.desktopPrinterConnection?.(data);
 };
 renderOverview=data=>{
  baseOverview(data);const m=data.monitor;
  el('overview-connection').textContent=label(m.state);
  if(m.connected&&['printing','paused'].includes(m.state)){
   el('overview-file').textContent=m.filename;
   if(data.last_preflight?.filename!==m.filename)el('overview-result').textContent=t('Текущая печать — проверка запуска не подтверждена','Current print — start check not confirmed','Aktueller Druck — Startprüfung nicht bestätigt','Поточний друк — перевірку запуску не підтверджено','Impresión actual — comprobación de inicio sin confirmar');
  }
 };
})();
