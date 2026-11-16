// Explain the viewed slice without treating it as the current job's saved plan.
(()=>{
 const text=(ru,en,de,uk,es)=>({ru,en,de,uk,es}[currentLang]||en);
 const source=node('p');source.id='desktop-forecast-source';source.className='forecast-footnote';
 document.querySelector('#slice-forecast .forecast-meta').after(source);
 window.desktopForecastSource=(entry,data)=>{
  source.textContent=entry?text('Источник','Source','Quelle','Джерело','Origen')+': Snorca · '+entry.source_label:'';
  source.title=entry?.source||'';
  if(entry&&data?.monitor.active_job_key)source.append(document.createTextNode(' · '+text(
   'Просмотр пластины — отдельно от плана текущей печати',
   'Viewed plate — separate from the current print plan',
   'Angezeigte Platte — getrennt vom aktuellen Druckplan',
   'Перегляд пластини — окремо від плану поточного друку',
   'Placa visualizada — independiente del plan de impresión actual')));
 };
})();
