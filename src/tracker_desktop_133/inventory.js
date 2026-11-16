// Reuse the published forms; attach safe 2.0 commands and assignment context.
(()=>{
 const compact=document.createElement('style');compact.textContent=`
 #view-spools .table-scroll{max-height:none;overflow:visible}
 #view-spools .spool-inventory{min-width:0;width:100%;table-layout:fixed}
 #view-spools .spool-inventory td,#view-spools .spool-inventory th{white-space:normal;overflow-wrap:anywhere;padding:10px 8px}
 #view-spools .spool-inventory td:last-child button{display:inline-block;margin:3px;padding:6px 9px;font-size:12px;line-height:1.35;min-height:30px;white-space:normal;max-width:100%}
 #view-spools .spool-inventory input{width:86px!important;max-width:100%;box-sizing:border-box;padding:6px}
 #view-spools .inventory-name>span{min-width:0}
 #view-spools .inventory-name .sm-art{flex-shrink:0}
 #inventory-toolbar{gap:8px}
 #inventory-toolbar button{padding:7px 10px;font-size:13px;line-height:1.35}
 #inventory-toolbar input:not([type=checkbox]){padding:8px 10px;min-width:140px}
 #inventory-toolbar input[type=checkbox]{width:auto;min-width:0;min-height:0}
 #view-spools .inventory-param-button{margin:3px}
 @media(max-width:800px){
 #view-spools .spool-inventory col{width:auto!important}
 #view-spools .inventory-name{gap:6px;flex-wrap:wrap}
 #view-spools .spool-inventory td,#view-spools .spool-inventory th{padding:8px 4px;font-size:12px}
 }
 `;document.body.append(compact);
 el('new-weight').step='any';el('new-weight').min='0';
 const text=(ru,en,de,uk,es)=>({ru,en,de,uk,es}[currentLang]||en);
 window.desktopConfirmInventory=(path,body)=>{
  if(path==='/api/spools/update')return confirm(text(
   'Установить остаток катушки: ','Set spool balance to: ','Spulenrest setzen auf: ','Встановити залишок котушки: ','Establecer el saldo de la bobina: ')+body.remaining_g+' g?');
  if(path==='/api/slots'||(path==='/api/spools/add'&&body.assign_slot)){
   const d=desktopFormData,p=d.printers.find(p=>p.id===d.selected_printer);
   const slots=path==='/api/slots'?body:{[body.assign_slot]:'new'};
   const rows=Object.entries(slots).map(([slot,id])=>'T'+(Number(slot)-1)+' → '+(id==='new'?body.name:id?(d.spools[id]?.name||id):'—'));
   return confirm(text('Подтвердите физическое расположение катушек','Confirm the physical spool positions','Physische Spulenpositionen bestätigen','Підтвердьте фізичне розташування котушок','Confirme las posiciones físicas de las bobinas')+'\n'+(p?.name||d.selected_printer)+'\n'+rows.join('\n'));
  }
  return true;
 };
 window.desktopInventoryLoaded=d=>{
  desktopFormData=d;
  for(const row of document.querySelectorAll('#spools-table tr')){
   const s=d.spools[row.dataset.spoolId];if(!s)continue;
   const labels=(s.assignments||[]).map(a=>a.printer_name+' · T'+a.channel+
    (['recognized','manual_confirmed'].includes(a.state)?'':' · '+text('требует проверки','needs review','Prüfung erforderlich','потребує перевірки','requiere revisión')));
   const mark=node('small',labels.length?labels.join('; '):text('Не назначена','Unassigned','Nicht zugewiesen','Не призначена','Sin asignar'));
   mark.className='uid-inventory-assignments';row.querySelector('.inventory-name>span')?.append(mark);
   if(s.uid)row.querySelector('.inventory-name>span')?.append(node('small','UID '+s.uid));
   row.dataset.search+=' '+labels.join(' ')+' '+(s.uid||'');
  }
  // Initial language is loaded asynchronously; refresh labels immediately too.
  void window.refreshSliceForecast?.(false);
 };
})();
