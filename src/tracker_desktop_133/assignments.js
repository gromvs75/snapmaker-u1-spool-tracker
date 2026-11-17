// Explicit physical placement, independent of balances and usage accounting.
(()=>{
 const t=desktopText,form=el('slots-form'),message=node('p');message.id='desktop-assignment-result';message.setAttribute('role','status');form.append(message);let busy=false;
 const selected=()=>Object.fromEntries([1,2,3,4].map(i=>[String(i),form.querySelector(`[name=slot_${i}]`).value]));
 function restore(values){for(const [i,value] of Object.entries(values)){const select=form.querySelector(`[name=slot_${i}]`);if([...select.options].some(o=>o.value===value)){select.value=value;select.dispatchEvent(new Event('change'))}}}
 const conflict=()=>t('Назначения не сохранены. Данные обновлены автоматически; выбранные катушки сохранены в форме. Проверьте расположение и подтвердите снова.','Assignments not saved. Data refreshed automatically; your spool selections remain in the form. Review the positions and confirm again.','Zuordnungen nicht gespeichert. Daten automatisch aktualisiert; die Spulenauswahl bleibt im Formular. Positionen prüfen und erneut bestätigen.','Призначення не збережено. Дані оновлено автоматично; вибрані котушки залишилися у формі. Перевірте розташування та підтвердьте знову.','Asignaciones no guardadas. Datos actualizados automáticamente; se conserva la selección. Revise las posiciones y confirme de nuevo.');
 form.addEventListener('submit',async event=>{
  event.preventDefault();event.stopImmediatePropagation();if(busy)return;busy=true;el('t-save-slots').disabled=true;
  const proposal=selected(),printer=desktopFormData.selected_printer;
  message.textContent=t('Проверяем актуальные назначения…','Checking current assignments…','Aktuelle Zuordnungen werden geprüft…','Перевіряємо поточні призначення…','Comprobando asignaciones actuales…');
  try{
   await loadData();
   if(desktopFormData.selected_printer!==printer)throw Error(t('Выбран другой принтер. Проверьте его назначения.','A different printer is selected. Review its assignments.','Ein anderer Drucker ist ausgewählt. Zuordnungen prüfen.','Вибрано інший принтер. Перевірте його призначення.','Se seleccionó otra impresora. Revise sus asignaciones.'));
   restore(proposal);
   if(Object.values(proposal).some(id=>id&&!desktopFormData.spools[id]))throw Error(conflict());
   const response=await fetch('/api/slots',{method:'POST',headers:{'Content-Type':'application/json'},trackerInventoryRevision:desktopFormData.inventory_revision,body:JSON.stringify(proposal)});
   const result=await response.json();
   if(!response.ok){
    if(response.status===409&&result.error?.startsWith('Катушки или назначения изменились')){
     await loadData();if(desktopFormData.selected_printer===printer)restore(proposal);message.textContent=conflict();return;
    }
    if(result.error==='Нет связи с принтером или печать не завершена. Назначение не подтверждено.')throw Error(t('Подключите принтер и дождитесь завершения печати. Ручное назначение не требует модуля RFID/UID.','Connect the printer and wait for printing to finish. Manual assignment does not require an RFID/UID module.','Drucker verbinden und Druckende abwarten. Manuelle Zuordnung benötigt kein RFID/UID-Modul.','Підключіть принтер і дочекайтеся завершення друку. Ручне призначення не потребує модуля RFID/UID.','Conecte la impresora y espere a que termine la impresión. La asignación manual no requiere un módulo RFID/UID.'));
    throw Error(result.error||String(response.status));
   }
   if(!result.status){message.textContent='';return} // Cancelled before any write.
   await loadData();
   message.textContent=t('Расположение подтверждено. Остатки не изменены; расход не списывался.','Positions confirmed. Balances unchanged; no usage deducted.','Positionen bestätigt. Restmengen unverändert; kein Verbrauch abgebucht.','Розташування підтверджено. Залишки не змінено; витрати не списувалися.','Posiciones confirmadas. Saldos sin cambios; no se descontó consumo.');
  }catch(error){message.textContent=error.message}
  finally{busy=false;el('t-save-slots').disabled=false}
 },true);
})();
