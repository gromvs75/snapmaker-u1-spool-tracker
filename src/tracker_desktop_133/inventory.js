// Reuse the published forms; attach safe 2.0 commands and assignment context.
(()=>{
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
