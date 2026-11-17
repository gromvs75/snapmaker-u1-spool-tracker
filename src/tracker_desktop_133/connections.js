// Keep the published connection form; persist a list of stable printer identities.
(()=>{
 const t=desktopText,form=el('printer-form');let data=null,draft=false,busy=false;
 const nameLabel=node('label'),name=node('input');name.id='desktop-printer-name';name.maxLength=100;nameLabel.style.cssText='display:flex;align-items:center;gap:12px;margin-bottom:14px';nameLabel.append(name);form.prepend(nameLabel);
 const add=node('button'),toggle=node('button'),message=node('p');add.type=toggle.type='button';add.id='desktop-printer-add';toggle.id='desktop-connections-toggle';message.id='desktop-connections-message';message.className='subtitle';
 el('desktop-printer-picker').after(add);form.querySelector('.printer-actions').append(toggle);form.append(message);
 const style=node('style');style.textContent='#desktop-printer-context button{padding:7px 12px;font-size:13px;line-height:1.3;border-radius:8px;background:var(--input);border:1px solid var(--border);margin:0;white-space:normal} #view-settings .printer-actions button{padding:8px 12px;font-size:14px;line-height:1.4;border-radius:8px}';document.body.append(style);
 // Connection lifecycle is explicit. Saving a URL never starts a collector.
 el('printer-enabled').closest('label').hidden=true;
 const base=window.desktopInventoryLoaded;
 window.desktopInventoryLoaded=d=>{base(d);data=d;draft=false;const p=d.printers.find(p=>p.id===d.selected_printer);
  nameLabel.firstChild?.nodeType===3&&nameLabel.firstChild.remove();nameLabel.prepend(document.createTextNode(t('Имя принтера','Printer name','Druckername','Назва принтера','Nombre de impresora')));name.value=p?.name||'';
  if(p){const u=new URL(p.url);el('printer-host').value=u.protocol==='http:'&&(!u.pathname||u.pathname==='/')?u.hostname:p.url;el('printer-port').value=u.port||(u.protocol==='https:'?443:80)}
  add.textContent=t('Добавить принтер','Add printer','Drucker hinzufügen','Додати принтер','Añadir impresora');
  toggle.textContent=d.connections?.connected?t('Остановить подключения','Stop connections','Verbindungen stoppen','Зупинити підключення','Detener conexiones'):t('Подключить принтеры','Connect printers','Drucker verbinden','Підключити принтери','Conectar impresoras');
  toggle.disabled=busy||!d.connections||!d.printers.length;add.disabled=busy||!!d.connections?.connected;
  if(d.monitor.connected&&d.monitor.state==='unknown')el('printer-status').textContent=t('Связь есть; состояние печати ещё не подтверждено','Connected; print state not yet confirmed','Verbunden; Druckstatus noch unbestätigt','Зв’язок є; стан друку ще не підтверджено','Conectada; estado de impresión aún sin confirmar');
  message.textContent=t('Адреса сохраняются отдельно. Подключение запускается кнопкой; после перезапуска оно остановлено.','Addresses are saved separately. Use Connect to start; connections stay stopped after restart.','Adressen werden getrennt gespeichert. Verbinden startet die Verbindung; nach Neustart bleibt sie gestoppt.','Адреси зберігаються окремо. Підключення запускається кнопкою; після перезапуску воно зупинене.','Las direcciones se guardan por separado. Conectar inicia las conexiones; al reiniciar permanecen detenidas.');
 };
 const url=()=>{const host=el('printer-host').value.trim();return host.includes('://')?host:'http://'+(host.includes(':')&&!host.startsWith('[')?'['+host+']':host)+':'+Number(el('printer-port').value)};
 add.onclick=()=>{el('nav-settings').click();document.querySelector('[data-settings-section=printer]').click();draft=true;name.value='';el('printer-host').value='';el('printer-port').value=7125;name.focus();message.textContent=t('Новый принтер. Заполните адрес и сохраните.','New printer. Enter its address and save.','Neuer Drucker. Adresse eingeben und speichern.','Новий принтер. Введіть адресу та збережіть.','Nueva impresora. Introduzca la dirección y guarde.')};
 async function work(fn){if(busy)return;busy=true;toggle.disabled=add.disabled=true;try{await fn()}catch(e){message.textContent=e.message}finally{busy=false;toggle.disabled=!data?.connections||!data?.printers.length;add.disabled=!!data?.connections?.connected}}
 form.addEventListener('submit',e=>{e.preventDefault();e.stopImmediatePropagation();work(async()=>{
  if(data.connections?.connected)throw Error(t('Сначала остановите подключения.','Stop connections first.','Zuerst Verbindungen stoppen.','Спочатку зупиніть підключення.','Detenga primero las conexiones.'));
  const id=!draft&&data.selected_printer?data.selected_printer:crypto.randomUUID(),p={id,name:name.value.trim(),url:url()};
  const printers=data.printers.filter(p=>p.id!==id).concat([p]);
  const expectedRevision=data.settings_revision,guardModes={...(data.guard_modes||{}),[id]:el('guard-mode').value};
  if(guardModes[id]==='strict'&&!await window.graphiteConfirm((guardText[currentLang]||guardText.en).confirm))return;
  await desktopCore('settings',{values:{printers,printer_names:Object.fromEntries(printers.map(p=>[p.id,p.name])),selected_printer:id,guard_modes:guardModes},expected_revision:expectedRevision});await loadData();window.reportSettingsSaved?.();
 })},true);
 const probe=el('printer-test'),probeResult=el('printer-test-result');let probeBusy=false,probeSequence=0;
 const clearProbe=()=>{probeSequence++;probeResult.textContent='';delete probeResult.dataset.state};
 add.addEventListener('click',clearProbe);
 for(const id of ['printer-host','printer-port','desktop-printer-picker'])el(id).addEventListener(id==='desktop-printer-picker'?'change':'input',clearProbe);
 probe.addEventListener('click',async e=>{
  e.preventDefault();e.stopImmediatePropagation();if(probeBusy)return;
  const sequence=++probeSequence,target=url();probeBusy=true;probe.disabled=true;
  probeResult.dataset.state='pending';probeResult.textContent=t('Проверяем соединение…','Checking connection…','Verbindung wird geprüft…','Перевіряємо з’єднання…','Comprobando conexión…')+' '+target;
  try{
   const result=await desktopCore('test_printer',{url:target});if(sequence!==probeSequence)return;
   probeResult.dataset.state='ok';
   const state=({printing:t('Печать идёт','Printing','Druck läuft','Друк триває','Imprimiendo'),paused:t('Пауза','Paused','Pausiert','Пауза','En pausa'),standby:t('Ожидание','Standby','Bereit','Очікування','En espera'),complete:t('Печать завершена','Print complete','Druck abgeschlossen','Друк завершено','Impresión finalizada')})[result.state]||result.state;
   probeResult.textContent=t('Moonraker отвечает','Moonraker responds','Moonraker antwortet','Moonraker відповідає','Moonraker responde')+' · '+state+' · '+(result.uid_available?t('Модуль UID доступен','UID module available','UID-Modul verfügbar','Модуль UID доступний','Módulo UID disponible'):t('Модуль UID не обнаружен','UID module not found','UID-Modul nicht gefunden','Модуль UID не знайдено','Módulo UID no encontrado'))+' · '+target+' · '+new Date().toLocaleTimeString(currentLang)+'. '+t('Разовая проверка; постоянное подключение не запускалось.','One-time check; continuous connection was not started.','Einmalige Prüfung; keine dauerhafte Verbindung gestartet.','Разова перевірка; постійне підключення не запускалося.','Comprobación puntual; no se inició una conexión continua.');
  }catch(error){if(sequence!==probeSequence)return;probeResult.dataset.state='error';probeResult.textContent=t('Не удалось проверить соединение: ','Connection check failed: ','Verbindungsprüfung fehlgeschlagen: ','Не вдалося перевірити з’єднання: ','No se pudo comprobar la conexión: ')+target+' · '+error.message}
  finally{probeBusy=false;probe.disabled=false}
 },true);
 toggle.onclick=()=>work(async()=>{const connected=data.connections.connected,expectedRevision=data.settings_revision;
  if(!connected&&!await window.graphiteConfirm(t('Подключить сохранённые принтеры?','Connect the saved printers?','Gespeicherte Drucker verbinden?','Підключити збережені принтери?','¿Conectar las impresoras guardadas?')+'\n'+data.printers.map(p=>p.name+' · '+p.url).join('\n')))return;
  await desktopCore(connected?'connections_stop':'connections_start',{confirmed:true,...(connected?{}:{expected_revision:expectedRevision})});await loadData();
 });
})();
