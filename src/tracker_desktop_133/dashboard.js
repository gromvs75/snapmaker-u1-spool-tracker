// Read-only dashboard. Navigation opens existing guarded forms; no new writes.
(()=>{
 const t=desktopText,card=document.querySelector('.overview-card');
 const words={unknown:()=>t('Нет данных','No data','Keine Daten','Немає даних','Sin datos'),
  remaining:()=>t('Осталось ≈','Remaining ≈','Verbleibend ≈','Залишилось ≈','Restante ≈'),
  balance:()=>t('Остаток неизвестен','Remaining unknown','Restmenge unbekannt','Залишок невідомий','Saldo desconocido')};
 const known=x=>typeof x==='number'&&Number.isFinite(x)&&x>=0;
 const duration=value=>{if(!known(value))return '—';const m=Math.ceil(value/60),h=Math.floor(m/60);return h?`${h} ${t('ч','h','Std.','год','h')} ${m%60} ${t('мин','min','Min.','хв','min')}`:`${m} ${t('мин','min','Min.','хв','min')}`};
 const telemetry=node('section',undefined,'dash-telemetry');telemetry.id='dashboard-telemetry';
 const percent=node('strong','—','dash-percent'),bar=node('progress');bar.max=100;bar.id='dashboard-progress';
 const layer=node('span',undefined,'dash-layer'),metrics=node('div',undefined,'dash-metrics'),hint=node('p',undefined,'dash-hint');
 const cells=['elapsed','remaining','finish'].map(id=>{const wrap=node('div'),label=node('small'),value=node('strong');value.id='dashboard-'+id;wrap.append(label,value);metrics.append(wrap);return {label,value}});
 const heading=card.querySelector('.overview-heading');
 heading.append(percent);
 telemetry.append(layer,bar,metrics,hint);
 heading.after(telemetry);
 function print(data){
  const m=data.monitor||{},age=Date.now()/1000-m.checked_at,fresh=m.connected&&age>=-5&&age<5;
  const p=fresh&&known(m.progress)&&m.progress<=1?m.progress:null;
  percent.textContent=p===null?'—':`${Math.min(m.state==='complete'?100:99,Math.floor(p*100))}%`;
  if(p===null){bar.removeAttribute('value');bar.classList.add('is-unknown')}else{bar.value=p*100;bar.classList.remove('is-unknown')}
  bar.setAttribute('aria-label',t('Прогресс печати','Print progress','Druckfortschritt','Прогрес друку','Progreso de impresión'));
  bar.setAttribute('aria-valuetext',p===null?words.unknown():percent.textContent);
  layer.textContent=fresh&&Number.isInteger(m.current_layer)&&m.total_layers>0?t('Слой','Layer','Schicht','Шар','Capa')+` ${m.current_layer} / ${m.total_layers}`:t('Прогресс задания','Job progress','Auftragsfortschritt','Прогрес завдання','Progreso del trabajo');
  cells[0].label.textContent=t('Время печати','Print time','Druckzeit','Час друку','Tiempo de impresión');cells[0].value.textContent=duration(fresh?m.elapsed_seconds:null);
  const eta=fresh&&m.state==='printing'&&known(m.remaining_seconds)?m.remaining_seconds:null;
  cells[1].label.textContent=words.remaining();cells[1].value.textContent=duration(eta);
  cells[2].label.textContent=t('Завершение ≈','Finishes ≈','Fertig ≈','Завершення ≈','Finaliza ≈');
  if(eta===null)cells[2].value.textContent='—';else{
   const end=new Date((m.checked_at+eta)*1000),today=new Date(),options={hour:'2-digit',minute:'2-digit'};
   if(end.toDateString()!==today.toDateString()){options.day='numeric';options.month='short'}
   cells[2].value.textContent=end.toLocaleString({ru:'ru-RU',en:'en-GB',de:'de-DE',uk:'uk-UA',es:'es-ES'}[currentLang]||'en-GB',options);
  }
  hint.textContent=!fresh?t('Ожидаем актуальные данные принтера','Waiting for live printer data','Warten auf aktuelle Druckerdaten','Очікуємо актуальні дані принтера','Esperando datos actuales de la impresora'):m.state==='paused'?t('На паузе — время завершения пока неизвестно','Paused — finish time is unknown','Pausiert — Endzeit unbekannt','На паузі — час завершення невідомий','En pausa — hora de finalización desconocida'):eta!==null?t('Оценка по текущему прогрессу; время может измениться','Estimate based on current progress; time may change','Schätzung anhand des Fortschritts; Zeit kann sich ändern','Оцінка за поточним прогресом; час може змінитися','Estimación según el progreso; el tiempo puede cambiar'):m.state==='printing'?t('Недостаточно данных для оценки времени','Not enough data to estimate time','Zu wenig Daten zur Zeitschätzung','Недостатньо даних для оцінки часу','Datos insuficientes para estimar el tiempo'):'';
 }
 function rfid(data,ch,spool){
  const reader=data.uid_channels?.[data.selected_printer]||{},channel=reader.channels?.[String(ch)]||{};
  if(!data.monitor?.connected)return t('RFID · нет связи','RFID · offline','RFID · offline','RFID · немає зв’язку','RFID · sin conexión');
  if(reader.state==='module_missing')return t('RFID · без модуля','RFID · no module','RFID · ohne Modul','RFID · без модуля','RFID · sin módulo');
  if(reader.state!=='ready')return t('RFID · недоступен','RFID · unavailable','RFID · nicht verfügbar','RFID · недоступний','RFID · no disponible');
  if(channel.state==='present')return spool&&data.slot_status?.[String(ch+1)]==='recognized'?t('RFID · распознана','RFID · recognized','RFID · erkannt','RFID · розпізнана','RFID · reconocida'):t('RFID · подтвердите метку','RFID · confirm tag','RFID · Tag bestätigen','RFID · підтвердьте мітку','RFID · confirme etiqueta');
  return ({absent:t('RFID · нет метки','RFID · no tag','RFID · kein Tag','RFID · немає мітки','RFID · sin etiqueta'),unreadable:t('RFID · ошибка чтения','RFID · read error','RFID · Lesefehler','RFID · помилка читання','RFID · error de lectura'),stale:t('RFID · данные устарели','RFID · stale data','RFID · Daten veraltet','RFID · дані застаріли','RFID · datos obsoletos'),conflict:t('RFID · конфликт меток','RFID · tag conflict','RFID · Tag-Konflikt','RFID · конфлікт міток','RFID · conflicto de etiquetas')})[channel.state]||t('RFID · проверяем','RFID · checking','RFID · wird geprüft','RFID · перевіряємо','RFID · comprobando');
 }
 let forecastPrinter=null, forecastRows=new Map();
 function heads(data){
  const m=data.monitor||{},age=Date.now()/1000-m.checked_at;
  [...el('sidebar-slots').querySelectorAll('.sidebar-slot')].forEach((head,i)=>{
   const spool=data.spools?.[data.slots?.[String(i+1)]],channel=data.uid_channels?.[data.selected_printer]?.channels?.[String(i)],tag=channel?.tag;
   const active=m.connected&&age>=-5&&age<5&&m.state==='printing'&&m.active_head===i;
   const sliceRow=forecastRows.get('T'+i);
   const estimate=data.selected_printer===forecastPrinter&&spool&&sliceRow?.spool_id===data.slots?.[String(i+1)]
      &&!(m.connected&&['printing','paused'].includes(m.state))?sliceRow:null;
   const signature=JSON.stringify([estimate,spool,channel?.state,channel?.uid,channel?.tag,data.slot_status?.[String(i+1)],rfid(data,i,spool),active,currentLang]);
   if(head.dataset.dashboard===signature)return;head.dataset.dashboard=signature;
   head.classList.toggle('selected-head',active);
   const color=spool?.color||(tag?.color?'#'+tag.color:null),safe=validColor(color)?color:null;
   const stripe=node('div',undefined,'dash-head-stripe'),id=node('strong','T'+i);stripe.append(id);
   if(safe){stripe.style.backgroundColor=safe;const rgb=[1,3,5].map(n=>parseInt(safe.slice(n,n+2),16));stripe.style.color=(rgb[0]*299+rgb[1]*587+rgb[2]*114)/1000>150?'#14171d':'#fff'}
   if(active)stripe.append(node('span',t('● Печатает','● Printing','● Druckt','● Друкує','● Imprimiendo'),'dash-active'));
   const info=node('div',undefined,'dash-spool-info'),art=node('span',undefined,'dash-spool-art'),copy=node('div');art.append(window.trackerSpoolArt(safe));
   copy.append(node('strong',spool?.material||tag?.material||'—'),node('span',spool?.name||t('Катушка не назначена','No spool assigned','Keine Spule zugewiesen','Котушку не призначено','Sin bobina asignada')));info.append(art,copy);
   const balance=node('div',undefined,'dash-balance'),remaining=known(spool?.remaining_g)?spool.remaining_g:null;
   const capacity=spool?.rfid?.nominal_weight_g??spool?.nominal_weight_g;
   const total=known(capacity)&&capacity>0?capacity:null;
   balance.append(node('strong',remaining===null?words.balance():displayGrams(remaining)+' '+gramUnit(),'head-remaining'));
   if(total!==null)balance.append(node('span',' / '+displayGrams(total)+' '+gramUnit()));
   const meter=node('div',undefined,'dash-balance-track');
   if(remaining!==null&&total!==null){const fill=node('span');fill.style.width=Math.max(0,Math.min(100,remaining/total*100))+'%';meter.append(fill);meter.classList.toggle('is-low',remaining/total<=.1);meter.setAttribute('role','meter');meter.setAttribute('aria-label',t('Остаток катушки','Spool remaining','Spulenrest','Залишок котушки','Saldo de bobina'));meter.setAttribute('aria-valuemin','0');meter.setAttribute('aria-valuemax',String(total));meter.setAttribute('aria-valuenow',String(Math.min(total,remaining)))}else meter.classList.add('is-unknown');
   const note=node('small',remaining===null?'':total===null?t('Номинальная масса неизвестна','Nominal weight unknown','Nenngewicht unbekannt','Номінальна маса невідома','Peso nominal desconocido'):t('Остаток по учёту','Tracked remaining','Erfasste Restmenge','Залишок за обліком','Saldo registrado'),'dash-balance-note');
   const statuses=node('div',undefined,'dash-head-status'),tagButton=node('button',rfid(data,i,spool),'dash-status-button');tagButton.type='button';tagButton.onclick=()=>el('desktop-tags-open').click();statuses.append(tagButton);
   const sm=spool?.spoolman,smButton=node('button',sm?'Spoolman #'+sm.id+(spool.pending_deliveries?' · '+t('очередь','pending','ausstehend','черга','pendiente')+' '+spool.pending_deliveries:' · '+t('привязана','linked','verknüpft','прив’язана','vinculada')):spool?t('Локальный учёт','Local tracking','Lokale Erfassung','Локальний облік','Registro local'):t('Spoolman · не привязана','Spoolman · not linked','Spoolman · nicht verknüpft','Spoolman · не прив’язана','Spoolman · sin vincular'),'dash-status-button');
   smButton.type='button';smButton.onclick=()=>{el('nav-settings').click();document.querySelector('[data-settings-section=spoolman]').click()};statuses.append(smButton);
   if(spool&& !['recognized','manual_confirmed'].includes(data.slot_status?.[String(i+1)]))statuses.append(node('small',t('Назначение требует проверки','Assignment needs review','Zuordnung prüfen','Призначення потребує перевірки','Revise la asignación'),'dash-warning'));
   const children=[stripe,info,balance,meter,note];
   if(estimate){
    const used=t('По нарезке','Slice usage','Slicing-Verbrauch','За нарізкою','Consumo previsto')+' '+estimate.used.toLocaleString(currentLang,{maximumFractionDigits:3})+' '+gramUnit();
    const result=estimate.unknown?words.balance():estimate.enough
     ? t('После ≈','After ≈','Danach ≈','Після ≈','Después ≈')+' '+displayGrams(estimate.after)+' '+gramUnit()
     : t('Не хватает с резервом','Short with reserve','Fehlt mit Reserve','Не вистачає із запасом','Falta con reserva')+' '+displayGrams(estimate.deficit)+' '+gramUnit();
    const preview=node('div',undefined,'dash-head-forecast '+(estimate.unknown?'unknown':estimate.enough?'ok':'shortage'));
    preview.append(node('small',used),node('strong',result));
    children.push(preview);
   }
   head.replaceChildren(...children,statuses);
  });
 }
 const overview=renderOverview;renderOverview=data=>{overview(data);print(data)};
 let latest=null;
 window.desktopForecastHeads=(printer,rows)=>{
  forecastPrinter=printer;
  forecastRows=new Map(rows.map(row=>[row.tool,row]));
  if(latest)heads(latest);
 };
 const sidebar=renderSidebar;renderSidebar=data=>{latest=data;sidebar(data);heads(data)};
 const loaded=window.desktopInventoryLoaded;window.desktopInventoryLoaded=data=>{latest=data;loaded(data);print(data);heads(data)};
 // Forecast may rebuild the original four cards without changing inventory.
 new MutationObserver(()=>{if(latest)heads(latest)}).observe(el('sidebar-slots'),{childList:true});
})();
