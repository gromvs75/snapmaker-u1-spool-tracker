// A single printer context for the original overview, inventory and history.
(()=>{
 const text=(ru,en,de,uk,es)=>({ru,en,de,uk,es}[currentLang]||en);
 const row=node('div');row.id='desktop-printer-context';row.style.cssText='display:flex;align-items:center;gap:12px;margin:-8px 0 24px;flex-wrap:wrap';
 const label=node('label'),picker=node('select'),status=node('span');picker.id='desktop-printer-picker';picker.style.width='min(320px, 100%)';label.htmlFor=picker.id;status.className='subtitle';
 row.append(label,picker,status);document.querySelector('.header-bar').after(row);
 const base=window.desktopInventoryLoaded;
 window.desktopInventoryLoaded=data=>{
  base(data);
  label.textContent=text('Принтер','Printer','Drucker','Принтер','Impresora');
  picker.replaceChildren();
  for(const p of data.printers){const o=node('option',p.name);o.value=p.id;picker.append(o)}
  picker.value=data.selected_printer;picker.disabled=!data.printers.length;
  status.textContent=data.monitor.connected?
   text('Есть связь','Connected','Verbunden','Є зв’язок','Conectada'):
   text('Подключения остановлены / нет связи','Connections stopped / offline','Verbindungen gestoppt / offline','Підключення зупинені / немає зв’язку','Conexiones detenidas / sin conexión');
 };
 picker.onchange=()=>act(async()=>{
  const selected=picker.value;picker.disabled=true;
  try{await api('/api/select_printer',{selected_printer:selected});await loadData();await window.refreshSliceForecast?.(false)}
  finally{picker.disabled=false;picker.value=desktopFormData?.selected_printer||''}
 });
})();
