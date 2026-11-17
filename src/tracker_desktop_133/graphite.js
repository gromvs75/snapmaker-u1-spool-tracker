// Presentation adapter only. Existing nodes keep their listeners, form ownership,
// revisions, idempotency keys and five-language rendering. No network writes.
(()=>{
 document.body.classList.add('graphite');
 const t=desktopText;
 const heads=document.querySelector('#view-overview .sidebar');
 // User-approved order: observed print -> heads/spools -> independent forecast.
 document.querySelector('.overview-card').after(heads);
 const tags=el('desktop-tags-open');
 if(tags)el('desktop-printer-context').append(tags);
 const footer=node('footer',undefined,'graphite-footer');
 const identity=node('span'),spoolman=node('button');spoolman.type='button';
 spoolman.onclick=()=>{el('nav-settings').click();document.querySelector('[data-settings-section=spoolman]').click();document.querySelector('[data-sm-tab=usage]').click()};
 footer.append(identity,spoolman);document.querySelector('.container').append(footer);
 const sm=el('spoolman-panel');sm.querySelector('h2').textContent='Spoolman';
 const catalogToolbar=node('div',undefined,'graphite-catalog-toolbar');
 const search=el('sm-search');search.before(catalogToolbar);catalogToolbar.append(search);
 const compare=el('sm-inspector-actions').querySelector('.sc-open');
 if(compare)catalogToolbar.append(compare);
 catalogToolbar.append(el('sm-refresh-selected'));
 const columns=node('div',undefined,'graphite-catalog-columns');
 const columnLabels=[node('span'),node('span'),node('span')];columns.append(...columnLabels);
 el('sm-visual-list').before(columns);
 function catalog(){
  const records=desktopSpoolmanData?.state?.catalog||{};
  for(const row of el('sm-visual-list').querySelectorAll('.sm-spool-row')){
   if(row.querySelector('.graphite-material'))continue;
   const record=records[row.dataset.spoolId];if(!record)continue;
   const material=node('span',record.material||'—','graphite-material');
   row.querySelector('.sm-weight').before(material);
  }
 }
 new MutationObserver(catalog).observe(el('sm-visual-list'),{childList:true});
 function language(){
  identity.textContent='Tracker '+DESKTOP_VERSION+' · '+t('кандидат','candidate','Kandidat','кандидат','candidato');
  spoolman.textContent=t('Spoolman · передача расхода','Spoolman · usage delivery','Spoolman · Verbrauchsübertragung','Spoolman · передача витрат','Spoolman · envío de consumo');
  // Keep the full product/module information available without a tall header.
  const subtitle=el('t-subtitle');subtitle.title=subtitle.textContent;
  columnLabels[0].textContent=t('Катушки Spoolman','Spoolman spools','Spoolman-Spulen','Котушки Spoolman','Bobinas Spoolman');
  columnLabels[1].textContent=t('Материал','Material','Material','Матеріал','Material');
  columnLabels[2].textContent=t('Остаток','Remaining','Restmenge','Залишок','Restante');
 }
 function art(data){
  for(const [index,head] of [...el('sidebar-slots').querySelectorAll('.sidebar-slot')].entries()){
   const spool=data.spools?.[data.slots?.[String(index+1)]];
   const visual=head.querySelector('.printhead-visual');if(!visual||visual.querySelector('.graphite-head-art'))continue;
   const image=node('span',undefined,'graphite-head-art');image.append(window.trackerSpoolArt(spool?.color));visual.append(image);
   if(spool){const state=data.slot_status?.[String(index+1)];head.append(node('small',state==='recognized'?t('Метка распознана','Tag recognized','Tag erkannt','Мітку розпізнано','Etiqueta reconocida'):state==='manual_confirmed'?t('Назначение подтверждено','Assignment confirmed','Zuordnung bestätigt','Призначення підтверджено','Asignación confirmada'):t('Назначение требует проверки','Assignment needs review','Zuordnung prüfen','Призначення потребує перевірки','Revise la asignación'),'graphite-assignment'))}
   if(spool?.uid)head.append(node('div','UID '+spool.uid,'graphite-uid'));
  }
 }
 let headData=null;
 const sidebar=renderSidebar;renderSidebar=data=>{headData=data;sidebar(data);art(data)};
 // Forecast selection also rebuilds cards through its captured original renderer.
 // Observe only replacement of the four cards, not our decorative descendants.
 new MutationObserver(()=>{if(headData)art(headData)}).observe(el('sidebar-slots'),{childList:true});
 if(desktopFormData)art(desktopFormData);
 // A light DOM observer localizes only new chrome, never replaces forms/data.
 new MutationObserver(language).observe(el('nav-settings'),{childList:true});language();
})();
