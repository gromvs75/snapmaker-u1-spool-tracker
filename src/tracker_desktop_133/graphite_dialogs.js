// Complete the approved atlas around existing controls. No accounting policy here.
(()=>{
 const t=desktopText, bindings=[];
 const label=(e,...words)=>{const update=()=>e.textContent=t(...words);bindings.push(update);update();return e};
 const button=(text,fn,cls='gd-secondary')=>{const b=node('button',text,cls);b.type='button';b.onclick=fn;return b};
 const closeText=()=>t('Закрыть','Close','Schließen','Закрити','Cerrar');
 const cancelText=()=>t('Отмена','Cancel','Abbrechen','Скасувати','Cancelar');
 function frame(d,title,bodyNodes,actions=[],subtitle=null,close=null){
  d.classList.add('graphite-dialog');
  const header=node('header',undefined,'gd-header'),copy=node('div'),body=node('div',undefined,'gd-body'),foot=node('footer',undefined,'gd-footer');
  if(!title.id)title.id=d.id+'-title';d.setAttribute('aria-labelledby',title.id);copy.append(title);if(subtitle)copy.append(subtitle);
  close=close||label(button(closeText(),()=>d.close()),'Закрыть','Close','Schließen','Закрити','Cerrar');close.classList.add('gd-close');close.setAttribute('aria-label',close.textContent);if(!close.dataset.gdLabel){close.dataset.gdLabel='true';new MutationObserver(()=>close.setAttribute('aria-label',close.textContent)).observe(close,{childList:true})}header.append(copy,close);
  body.append(...bodyNodes);foot.append(...actions);foot.hidden=!actions.length;d.replaceChildren(header,body,foot);
  return {header,body,foot};
 }
 const field=(input,...words)=>{const l=node('label',undefined,'gd-field');l.append(label(node('span'),...words),input);return l};
 const cancel=d=>button(cancelText(),()=>d.close());
 const two=(...items)=>{const e=node('div',undefined,'gd-two');e.append(...items);return e};
 // Saved-plan states all use the same structure; original decisions/revisions survive.
 window.graphiteHistoryDialog=d=>{
  const h=d.querySelector('.uid-history-heading'),title=h.querySelector('h2'),close=h.querySelector('button');
  const groups=[...d.querySelectorAll(':scope > .uid-history-actions')],actions=groups.flatMap(g=>[...g.children]);
  const closing=d.querySelector(':scope > button');if(closing)actions.push(closing);
  const nodes=[...d.children].filter(n=>n!==h&&!groups.includes(n)&&n!==closing);
  const primary=actions.find(b=>b.classList.contains('uid-history-primary'));if(primary){actions.splice(actions.indexOf(primary),1);actions.push(primary)}
  if(!actions.length)actions.push(button(closeText(),()=>d.close()));else if(actions.length===1)actions.unshift(cancel(d));
  const {body}=frame(d,title,nodes,actions,null,close);d.classList.add('gd-wide');
  const fields=[...body.children].filter(n=>n.tagName==='LABEL');
  if(fields.length){const grid=node('div',undefined,'gd-two');fields[0].before(grid);for(const f of fields){f.classList.add('gd-field');if(!f.querySelector('.uid-extra-amount'))f.classList.add('gd-span');grid.append(f)}}
 };
 window.graphiteUnlockDialog=d=>{
  const close=d.firstElementChild,title=d.querySelector('h2'),sub=title.nextElementSibling,apply=el('desktop-unlock-apply'),mode=el('desktop-unlock-mode');
  const nodes=[...d.children].filter(n=>![close,title,sub,apply].includes(n));
  const f=frame(d,title,nodes,[cancel(d),apply],sub,close);apply.classList.add('gd-primary');
  const modeField=field(mode,'Срок разрешения','Permission duration','Dauer der Freigabe','Строк дозволу','Duración del permiso');f.body.insertBefore(modeField,f.body.querySelector('label'));
  f.body.querySelector('p')?.classList.add('gd-notice');
 };
 window.graphiteDeliveryDialog=(d,row)=>{
  const close=el('desktop-delivery-close'),title=d.querySelector('h2'),sub=title.nextElementSibling;
  const note=el('desktop-delivery-note'),message=el('desktop-delivery-message'),actions=message.previousElementSibling;
  const nodes=[...d.children].filter(n=>![close,title,sub,actions].includes(n));
  const f=frame(d,title,nodes,[...actions.children],sub,close);d.classList.add('gd-wide');f.body.querySelector('p')?.classList.add('gd-notice');
  const explanation=note.previousElementSibling;explanation.id='desktop-delivery-note-label';note.setAttribute('aria-labelledby',explanation.id);
  // Keep existing decision buttons/handlers, but only a single emphasized send action.
  for(const b of f.foot.children)b.classList.add(b.id==='desktop-delivery-send'||b.id==='desktop-delivery-approve'?'gd-primary':'gd-secondary');
  if(['held','uncertain'].includes(row.state)){
   const decisions=[...f.foot.children],group=node('div',undefined,'gd-decisions');group.setAttribute('role','radiogroup');group.setAttribute('aria-label',t('Решение','Decision','Entscheidung','Рішення','Decisión'));let selected=null;
   const apply=button(t('Подтвердить решение','Confirm decision','Entscheidung bestätigen','Підтвердити рішення','Confirmar decisión'),()=>{if(selected&&!apply.disabled)selected()},'gd-primary');apply.id='graphite-delivery-confirm';
   const validate=()=>apply.disabled=!selected||!el('desktop-delivery-ack').checked||!note.value.trim();window.graphiteDeliveryValidate=validate;
   for(const b of decisions){const action=b.onclick;b.className='gd-decision';b.setAttribute('role','radio');b.setAttribute('aria-checked','false');b.onclick=()=>{selected=action;for(const other of decisions)other.setAttribute('aria-checked',String(other===b));validate()};group.append(b)}
   f.body.append(group);f.foot.append(cancel(d),apply);el('desktop-delivery-ack').addEventListener('change',validate);note.addEventListener('input',validate);validate();
  }else window.graphiteDeliveryValidate=()=>{};
  if(!f.foot.children.length){f.foot.hidden=false;f.foot.append(cancel(d))}
 };
 // Add spool: retain the real form and original color/assignment callbacks.
 const add=el('inventory-add-dialog'),form=el('add-spool-form'),oldTitle=el('t-add-hdr'),close=add.querySelector('.dialog-close'),submit=el('t-add-btn');
 const title=label(node('h2'),'Новая катушка','New spool','Neue Spule','Нова котушка','Nueva bobina');oldTitle.hidden=true;
 const name=field(el('new-name'),'Название','Name','Name','Назва','Nombre');
 const material=field(el('new-mat'),'Материал','Material','Material','Матеріал','Material');
 const mass=field(el('new-weight'),'Остаток, г','Remaining, g','Restmenge, g','Залишок, г','Restante, g');
 const color=el('new-color-picker'),head=el('create-head-row');form.replaceChildren(name,two(material,mass),color,head,oldTitle);submit.setAttribute('form',form.id);
 const addCancel=label(cancel(add),'Отмена','Cancel','Abbrechen','Скасувати','Cancelar');submit.classList.add('gd-primary');
 frame(add,title,[form],[addCancel,submit],label(node('p'),'Добавьте в библиотеку или назначьте на головку.','Add to the library or assign to a toolhead.','Zur Bibliothek hinzufügen oder einem Druckkopf zuweisen.','Додайте до бібліотеки або призначте голівці.','Añada a la biblioteca o asigne a un cabezal.'),close);
 // Comparison keeps source filters, fresh-catalog checks and local-only rename.
 const compare=el('sc-dialog'),ct=el('sc-title'),intro=el('sc-intro'),cc=el('sc-close'),layout=compare.querySelector('.sc-layout'),oldFoot=compare.querySelector('.sc-footer'),sync=el('sc-sync');
 frame(compare,ct,[layout,oldFoot.querySelector('p')],[el('sc-settings'),sync],intro,cc);compare.classList.add('gd-wide');sync.classList.add('gd-primary');
 // Restore always shows file -> validation -> explicit confirmation in that order.
 const backup=el('desktop-backup-dialog'),bc=el('desktop-backup-close'),bt=backup.querySelector('h2'),apply=el('desktop-backup-apply');
 const original=[...backup.children].filter(n=>![bc,bt,apply].includes(n)&&n.tagName!=='BR');
 frame(backup,bt,original,[label(cancel(backup),'Отмена','Cancel','Abbrechen','Скасувати','Cancelar'),apply],null,bc);apply.classList.add('gd-primary');
 backup.querySelector('.gd-body>p')?.classList.add('gd-notice');
 const file=el('desktop-backup-file'),choose=el('desktop-backup-choose'),filename=choose.nextElementSibling,check=el('desktop-backup-check'),files=node('div',undefined,'gd-file');
 choose.before(files);files.append(choose,filename,check);file.setAttribute('aria-label',t('Резервная копия','Backup','Sicherung','Резервна копія','Copia de seguridad'));
 // UID drawer is kept open by the existing queue, with grouped content and footer.
 const tags=el('desktop-tags-dialog'),tagClose=el('desktop-tags-close'),tagTitle=tags.querySelector('h2'),tagSave=el('desktop-tag-save'),tagRefresh=el('desktop-tags-refresh'),tagForm=tags.querySelector('form');
 tagForm.id='desktop-tag-form';tagSave.setAttribute('form',tagForm.id);tagSave.classList.add('gd-primary');
 frame(tags,tagTitle,[...tags.children].filter(n=>![tagClose,tagTitle,tagRefresh].includes(n)),[tagRefresh,el('desktop-tag-back'),el('desktop-tag-next'),tagSave],null,tagClose);
 tags.classList.add('gd-drawer');
 const ack=el('desktop-tag-ack');ack.parentElement.classList.add('gd-check');
 // No editable tag data is hidden; unavailable registration remains explained inline.
 const tagSteps=node('div',undefined,'gd-steps');tags.querySelector('.gd-body').prepend(tagSteps);
 for(const [i,words] of [['1',['Метка','Tag','Tag','Мітка','Etiqueta']],['2',['Катушка','Spool','Spule','Котушка','Bobina']],['3',['Привязка','Attachment','Verknüpfung','Прив’язка','Vinculación']]]){const step=node('span');step.append(node('b',i),label(node('span'),...words));tagSteps.append(step)}
 const tagState=()=>{const ready=!tagForm.hidden,confirmed=tagForm.dataset.step==='confirm';[...tagSteps.children].forEach((n,i)=>n.classList.toggle('active',i===(confirmed?2:ready?1:0)))};
 new MutationObserver(tagState).observe(tagForm,{attributes:true,attributeFilter:['hidden','data-step']});ack.addEventListener('input',tagState);tagState();
 // Counters are a diagnostic dialog, not a stretched block inside printer settings.
 const counters=node('dialog');counters.id='graphite-counters-dialog';document.body.append(counters);
 const countersTitle=label(node('h2'),'Счётчики головок','Toolhead counters','Druckkopfzähler','Лічильники голівок','Contadores de cabezales');
 const content=el('heads-content');const refresh=label(button('',()=>el('heads-read').click()),'Обновить','Refresh','Aktualisieren','Оновити','Actualizar');
 frame(counters,countersTitle,[content],[label(cancel(counters),'Закрыть','Close','Schließen','Закрити','Cerrar'),refresh]);
 new MutationObserver(()=>{if(content.children.length&&!counters.open)counters.showModal()}).observe(content,{childList:true});
 // Backup page has two clear tasks, preserving the existing export/import owners.
 const backupPage=el('backup-title').closest('.card'),create=node('section',undefined,'gd-section gd-create-backup'),restore=node('section',undefined,'gd-section');
 create.append(label(node('h3'),'Создать копию','Create backup','Sicherung erstellen','Створити копію','Crear copia'),el('backup-help'),el('backup-export'));
 restore.append(label(node('h3'),'Восстановление','Restore','Wiederherstellen','Відновлення','Restaurar'),label(node('p',undefined,'subtitle'),'Копии 2.0 и импорт 1.3.3. Перед заменой сохраняется копия текущей базы.','2.0 backups and 1.3.3 import. The current database is backed up before replacement.','Sicherungen 2.0 und Import 1.3.3. Vor dem Ersetzen wird die aktuelle Datenbank gesichert.','Копії 2.0 та імпорт 1.3.3. Перед заміною зберігається копія поточної бази.','Copias 2.0 e importación 1.3.3. Se guarda la base actual antes de reemplazarla.'),el('backup-import'));
 backupPage.append(create,restore,el('backup-availability'));
 // A keyboard-accessible language dialog uses the same persisted language control.
 const picker=el('lang-picker'),languages=node('dialog');languages.id='graphite-language-dialog';document.body.append(languages);
 function openLanguages(){
  const list=node('div',undefined,'gd-language-list');
  for(const option of picker.options){const row=node('label'),radio=node('input');radio.type='radio';radio.name='graphite-language';radio.value=option.value;radio.checked=option.selected;row.append(node('span',option.textContent),radio);list.append(row)}
  const save=button(t('Сохранить выбор','Save selection','Auswahl speichern','Зберегти вибір','Guardar selección'),()=>{picker.value=list.querySelector('input:checked').value;languages.close();picker.dispatchEvent(new Event('change',{bubbles:true}))},'gd-primary');save.id='graphite-language-save';
  frame(languages,node('h2',t('Язык интерфейса','Interface language','Sprache der Oberfläche','Мова інтерфейсу','Idioma de la interfaz')),[list],[cancel(languages),save]);languages.showModal();list.querySelector('input:checked').focus();
 }
 picker.addEventListener('mousedown',e=>{e.preventDefault();openLanguages()});picker.addEventListener('keydown',e=>{if(['Enter',' ','ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();openLanguages()}});
 const paletteRender=renderNewColorPicker;
 renderNewColorPicker=()=>{paletteRender();const c=el('new-color').value;el('new-color-title').textContent=t('Цвет катушки: ','Spool color: ','Spulenfarbe: ','Колір котушки: ','Color de bobina: ')+(c||t('не выбран','not set','nicht gewählt','не вибрано','sin seleccionar'));el('new-color-grid').querySelector('.color-clear').textContent=t('Убрать цвет','Clear color','Farbe entfernen','Прибрати колір','Quitar color')};
 const localizeAdd=()=>{submit.textContent=head.hidden?t('Добавить катушку','Add spool','Spule hinzufügen','Додати котушку','Añadir bobina'):t('Добавить и назначить','Add and assign','Hinzufügen und zuweisen','Додати й призначити','Añadir y asignar');head.querySelector('span').textContent=t('Назначить на головку','Assign to toolhead','Druckkopf zuweisen','Призначити голівці','Asignar al cabezal');renderNewColorPicker()};
 new MutationObserver(localizeAdd).observe(add,{attributes:true,attributeFilter:['open']});
 bindings.push(()=>{localizeAdd();el('inventory-create-assign').textContent=t('Добавить и назначить','Add and assign','Hinzufügen und zuweisen','Додати й призначити','Añadir y asignar');
  const words=[['Библиотека','Library','Bibliothek','Бібліотека','Biblioteca'],['Головки T0–T3','Toolheads T0–T3','Druckköpfe T0–T3','Голівки T0–T3','Cabezales T0–T3']];document.querySelectorAll('.inventory-tabs button').forEach((b,i)=>{for(const n of [...b.childNodes])if(n.nodeType===3)n.remove();b.append(document.createTextNode(t(...words[i])));b.setAttribute('aria-label',t(...words[i]))})
 });
 // Localize the inherited settings chrome in all five supported languages.
 bindings.push(()=>{
  const sections=[['Принтер','Printer','Drucker','Принтер','Impresora'],['Spoolman','Spoolman','Spoolman','Spoolman','Spoolman'],['Учёт','Accounting','Verbrauch','Облік','Consumo'],['Резервная копия','Backup','Sicherung','Резервна копія','Copia de seguridad']];
  document.querySelectorAll('.settings-nav button').forEach((b,i)=>{for(const n of [...b.childNodes])if(n.nodeType===3)n.remove();b.append(document.createTextNode(t(...sections[i])));b.setAttribute('aria-label',t(...sections[i])) });
  const tabs=[['Подключение','Connection','Verbindung','Підключення','Conexión'],['Катушки','Spools','Spulen','Котушки','Bobinas'],['Передача расхода','Usage delivery','Verbrauchsübertragung','Передача витрат','Envío de consumo']];document.querySelectorAll('.settings-tabs button').forEach((b,i)=>b.textContent=t(...tabs[i]));
  for(const [id,words] of [['settings-account-title',['Учёт','Accounting','Verbrauch','Облік','Consumo']],['accounting-save',['Сохранить настройки учёта','Save accounting settings','Verbrauchseinstellungen speichern','Зберегти налаштування обліку','Guardar ajustes de consumo']],['sm-inspector-title',['Назначение катушки','Spool assignment','Spulenzuweisung','Призначення котушки','Asignación de bobina']],['sm-head-label',['Головка принтера','Toolhead','Druckkopf','Голівка принтера','Cabezal']],['sm-detach-selected',['Отвязать от Tracker','Detach from Tracker','Von Tracker trennen','Відв’язати від Tracker','Desvincular de Tracker']],['sm-refresh-selected',['Обновить каталог','Refresh catalog','Katalog aktualisieren','Оновити каталог','Actualizar catálogo']]])el(id).textContent=t(...words);
 });
 // Toolhead assignments: four readable rows, retaining selects/color shortcuts.
 const loaded=window.desktopInventoryLoaded;
 window.desktopInventoryLoaded=data=>{
  loaded(data);
  for(const [i,row] of [...el('slots-container').children].entries()){
   const badge=row.querySelector('.slot-badge'),select=row.querySelector('select'),control=row.querySelector('.slot-select-wrap'),choices=row.querySelector('details');
   badge.textContent='T'+i;select.setAttribute('aria-label','T'+i);
   const art=node('div',undefined,'gd-head-art'),copy=node('div',undefined,'gd-head-copy'),controls=node('div',undefined,'gd-head-controls');
   control.querySelector('.slot-selected-color').hidden=true;controls.append(control,choices);row.replaceChildren(badge,art,copy,controls);
   choices.querySelector('summary').textContent=t('Выбрать по цвету','Choose by color','Nach Farbe wählen','Вибрати за кольором','Elegir por color');
   const paint=()=>{const spool=data.spools[select.value],assignment=spool?.assignments?.find(a=>a.printer_id===data.selected_printer&&a.channel===i);art.replaceChildren(window.trackerSpoolArt(spool?.color));copy.replaceChildren(node('strong',spool?.name||t('Катушка не назначена','No spool assigned','Keine Spule zugewiesen','Котушку не призначено','Sin bobina asignada')));
    if(spool)copy.append(node('small',(spool.material||'—')+' · '+displayGrams(spool.remaining_g)+' '+gramUnit()+(spool.uid?' · UID '+spool.uid:'')));
    copy.append(node('small',select.value!==(data.slots[i+1]||'')?t('Выбор ещё не сохранён','Selection not saved yet','Auswahl noch nicht gespeichert','Вибір ще не збережено','Selección sin guardar'):!spool?'':assignment?.state==='recognized'?t('Метка распознана','Tag recognized','Tag erkannt','Мітку розпізнано','Etiqueta reconocida'):assignment?.state==='manual_confirmed'?t('Подтверждено вручную','Confirmed manually','Manuell bestätigt','Підтверджено вручну','Confirmado manualmente'):t('Требует проверки','Needs review','Prüfung erforderlich','Потребує перевірки','Requiere revisión')));
   };select.addEventListener('change',paint);choices.querySelectorAll('button').forEach(b=>b.addEventListener('click',paint));paint();
  }
 };
 bindings.push(()=>{el('t-slots-hdr').textContent=t('Головки T0–T3','Toolheads T0–T3','Druckköpfe T0–T3','Голівки T0–T3','Cabezales T0–T3');el('t-save-slots').textContent=t('Подтвердить расположение','Confirm positions','Positionen bestätigen','Підтвердити розташування','Confirmar posiciones')});
 // Updating captions must not replace form nodes or their state.
 const language=()=>bindings.forEach(f=>f());new MutationObserver(language).observe(el('nav-settings'),{childList:true});language();
})();
// Async replacement for blocking OS confirmation boxes. Every caller awaits the
// result, retains its backend guard and sends nothing on Cancel/Escape/close.
(()=>{
 let queue=Promise.resolve();
 window.graphiteConfirm=message=>{
  const show=()=>new Promise(resolve=>{
   const t=desktopText,d=node('dialog');d.id='graphite-confirm-dialog';d.className='graphite-dialog';
   const lines=String(message).split('\n'),title=node('h2',lines.shift());title.id='graphite-confirm-title';d.setAttribute('aria-labelledby',title.id);
   const header=node('header',undefined,'gd-header'),body=node('div',undefined,'gd-body'),footer=node('footer',undefined,'gd-footer');
   const close=node('button','×','gs-close'),cancel=node('button',t('Отмена','Cancel','Abbrechen','Скасувати','Cancelar'),'gd-secondary'),approve=node('button',t('Подтвердить','Confirm','Bestätigen','Підтвердити','Confirmar'),'gd-primary');
   approve.id='graphite-confirm-apply';cancel.id='graphite-confirm-cancel';close.setAttribute('aria-label',t('Закрыть','Close','Schließen','Закрити','Cerrar'));
   for(const b of [close,cancel,approve])b.type='button';
   const finish=value=>{d.close();d.remove();resolve(value)};close.onclick=cancel.onclick=()=>finish(false);approve.onclick=()=>finish(true);d.addEventListener('cancel',e=>{e.preventDefault();finish(false)});
   header.append(title,close);for(const line of lines)body.append(node('p',line));body.hidden=!lines.length;footer.append(cancel,approve);d.append(header,body,footer);document.body.append(d);d.showModal();cancel.focus();
  });
  const result=queue.then(show);queue=result.then(()=>{},()=>{});return result;
 };
})();
