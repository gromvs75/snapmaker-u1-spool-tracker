// Explain the viewed slice without treating it as the current job's saved plan.
(()=>{
 const text=(ru,en,de,uk,es)=>({ru,en,de,uk,es}[currentLang]||en);
 const source=node('p');source.id='desktop-forecast-source';source.className='forecast-footnote';
 document.querySelector('#slice-forecast .forecast-meta').after(source);
 const provisional=node('p');provisional.id='desktop-forecast-provisional';provisional.className='forecast-footnote';source.after(provisional);
 window.desktopForecastSource=(entry,data)=>{
  source.textContent=entry?text('Источник','Source','Quelle','Джерело','Origen')+': Snorca · '+entry.source_label:'';
  source.title=entry?.source||'';
  provisional.hidden=!entry?.provisional;
  provisional.textContent=entry?.provisional?text(
   'Расчёт по сохранённым катушкам и остаткам. Перед печатью проверьте назначения в «Катушки → Головки T0–T3».',
   'Calculated from saved spools and balances. Before printing, check assignments in Spools → Heads T0–T3.',
   'Berechnet mit gespeicherten Spulen und Restmengen. Vor dem Druck Zuordnungen unter Spulen → Köpfe T0–T3 prüfen.',
   'Розрахунок за збереженими котушками й залишками. Перед друком перевірте призначення в «Котушки → Головки T0–T3».',
   'Cálculo con bobinas y saldos guardados. Antes de imprimir, revise las asignaciones en Bobinas → Cabezales T0–T3.'):'';
  if(entry&&data?.monitor.active_job_key)source.append(document.createTextNode(' · '+text(
   'Просмотр пластины — отдельно от плана текущей печати',
   'Viewed plate — separate from the current print plan',
   'Angezeigte Platte — getrennt vom aktuellen Druckplan',
   'Перегляд пластини — окремо від плану поточного друку',
   'Placa visualizada — independiente del plan de impresión actual')));
 };
})();
