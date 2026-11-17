// Register observed tags using the existing guarded UID service. No UID typing.
(()=>{
 const t=desktopText,button=(id,text,fn)=>{const b=node('button',text);b.id=id;b.type='button';b.onclick=()=>run(fn);return b};
 let rows=[],data=null,selected=null,preview=null,busy=false,request=null,reviewing=false;
 const open=button('desktop-tags-open','RFID / UID',async()=>{dialog.showModal();await refresh()});el('inventory-toolbar').append(open);
 const dialog=node('dialog');dialog.id='desktop-tags-dialog';dialog.className='inventory-dialog';dialog.style.cssText='margin:0 0 0 auto;height:100%;max-height:100%;width:min(460px,100%);border-radius:16px 0 0 16px';document.body.append(dialog);
 const title=node('h2'),steps=node('p'),queue=node('div'),known=node('details'),knownTitle=node('summary'),knownRows=node('div'),form=node('form'),error=node('p');error.id='desktop-tags-message';error.setAttribute('role','status');known.append(knownTitle,knownRows);
 const close=button('desktop-tags-close','',async()=>dialog.close()),refreshButton=button('desktop-tags-refresh','',refresh);dialog.append(close,title,steps,queue,known,form,error,refreshButton);
 const mode=node('select'),modeLabel=node('label'),existing=node('select'),name=node('input'),material=node('input'),mass=node('input'),ack=node('input'),save=node('button');
 mode.id='desktop-tag-mode';existing.id='desktop-tag-existing';name.id='desktop-tag-name';material.id='desktop-tag-material';mass.id='desktop-tag-mass';mass.type='number';mass.min=0;mass.step='0.001';ack.type='checkbox';ack.id='desktop-tag-ack';save.id='desktop-tag-save';save.type='submit';name.maxLength=material.maxLength=100;
 const next=button('desktop-tag-next','',async()=>{reviewing=true;ack.checked=false;validate()}),back=button('desktop-tag-back','',async()=>{reviewing=false;ack.checked=false;validate()}),attachment=node('div');attachment.id='desktop-tag-attachment';attachment.className='gd-notice';
 const labels=[node('label'),node('label'),node('label'),node('label')],ackLabel=node('label');modeLabel.append(mode);form.append(modeLabel);for(const [i,input] of [existing,name,material,mass].entries()){labels[i].append(input);form.append(labels[i])}ackLabel.append(ack);form.append(attachment,ackLabel,next,back,save);
 for(const label of [modeLabel,...labels,ackLabel])label.style.cssText='display:block;margin:14px 0';
 const caption=(label,input,text)=>{label.replaceChildren(document.createTextNode(text),input)};
 function language(){next.textContent=t('Проверить привязку','Review attachment','Verknüpfung prüfen','Перевірити прив’язку','Revisar vinculación');back.textContent=t('Назад','Back','Zurück','Назад','Atrás');title.textContent=t('Регистрация меток','Tag registration','Tag-Registrierung','Реєстрація міток','Registro de etiquetas');close.textContent=t('Закрыть','Close','Schließen','Закрити','Cerrar');refreshButton.textContent=t('Проверить снова','Check again','Erneut prüfen','Перевірити знову','Comprobar de nuevo');save.textContent=t('Сохранить и продолжить','Save and continue','Speichern und weiter','Зберегти та продовжити','Guardar y continuar');
  knownTitle.textContent=t('Распознанные метки','Recognized tags','Erkannte Tags','Розпізнані мітки','Etiquetas reconocidas');
  caption(modeLabel,mode,t('Способ регистрации','Registration mode','Registrierungsart','Спосіб реєстрації','Modo de registro'));
  const previous=mode.value;mode.replaceChildren(new Option(t('Новая катушка','New spool','Neue Spule','Нова котушка','Bobina nueva'),'new'),new Option(t('Существующая катушка','Existing spool','Vorhandene Spule','Наявна котушка','Bobina existente'),'existing'));mode.value=previous||'new';
  [t('Катушка','Spool','Spule','Котушка','Bobina'),t('Название','Name','Name','Назва','Nombre'),t('Материал','Material','Material','Матеріал','Material'),t('Остаток, г','Remaining, g','Rest, g','Залишок, г','Restante, g')].forEach((text,i)=>caption(labels[i],[existing,name,material,mass][i],text));
  caption(ackLabel,ack,t('Подтверждаю: эта метка закреплена на выбранной катушке.','I confirm this tag is attached to the selected spool.','Dieses Tag gehört zur ausgewählten Spule.','Підтверджую: ця мітка закріплена на вибраній котушці.','Confirmo que esta etiqueta está fijada a la bobina seleccionada.'));
 }
 async function run(fn){if(busy)return;busy=true;validate();error.textContent='';try{await fn()}catch(e){error.textContent=e.message}finally{busy=false;validate()}}
 async function refresh(){data=await desktopCore('state');rows=data.occupied.filter(r=>r.uid&&!r.spool);knownRows.replaceChildren();for(const r of data.occupied.filter(r=>r.uid&&r.spool)){const p=data.printers.find(p=>p.id===r.printer_id);knownRows.append(node('p',(p?.name||r.printer_id)+' · T'+r.channel+' · '+r.uid+' · '+r.spool.name+' · '+(r.usable?t('Подтверждена','Confirmed','Bestätigt','Підтверджена','Confirmada'):t('Нужна проверка','Needs review','Prüfung erforderlich','Потрібна перевірка','Requiere revisión'))))}known.hidden=!knownRows.children.length;known.open=!rows.length;preview=null;request=null;reviewing=false;ack.checked=false;language();draw();if(rows.length)await choose(rows.find(r=>key(r)===key(selected))||rows[0]);else{selected=null;error.textContent=t('Новых считанных меток нет. Состояние канала указано выше.','No new tags have been read. Channel status is shown above.','Keine neuen Tags gelesen. Der Kanalstatus steht oben.','Нових зчитаних міток немає. Стан каналу вказано вище.','No se han leído etiquetas nuevas. El estado del canal aparece arriba.')}await loadData()}
 const key=r=>r?[r.printer_id,r.channel,r.uid].join(':'):'';
 function draw(){queue.replaceChildren();for(const row of rows){const printer=data.printers.find(p=>p.id===row.printer_id);const b=button('',(printer?.name||row.printer_id)+' · T'+row.channel+' · '+row.uid,()=>choose(row));b.style.cssText='display:block;width:100%;text-align:left;margin:6px 0';b.dataset.uid=row.uid;b.setAttribute('aria-current',String(key(row)===key(selected)));queue.append(b)}}
 async function choose(row){selected=row;preview=null;request=null;reviewing=false;ack.checked=false;name.value=material.value=mass.value='';draw();
  preview=await desktopCore('tag_preview',{printer_id:row.printer_id,channel:row.channel,uid:row.uid});
  existing.replaceChildren(...preview.candidates.map(s=>new Option(s.name+' · '+displayGrams(s.remaining_mg/1000)+' g',s.spool_id)));
  mode.value=preview.can_create?'new':'existing';steps.textContent=(data.printers.find(p=>p.id===row.printer_id)?.name||row.printer_id)+' · T'+row.channel+' · UID '+row.uid;validate();
 }
 function validate(){const fresh=!!preview,newMode=mode.value==='new';form.hidden=!rows.length;mode.disabled=busy||!fresh;mode.options[0]&&(mode.options[0].disabled=!preview?.can_create);mode.options[1]&&(mode.options[1].disabled=!preview?.candidates.length);
  modeLabel.hidden=reviewing;labels[0].hidden=newMode||reviewing;for(let i=1;i<4;i++)labels[i].hidden=!newMode||reviewing;
  ackLabel.hidden=!reviewing;attachment.hidden=!reviewing;next.hidden=reviewing||!rows.length;back.hidden=!reviewing||!rows.length;save.hidden=!reviewing||!rows.length;
  attachment.textContent=selected?('T'+selected.channel+' · UID '+selected.uid+' → '+(newMode?name.value:existing.selectedOptions[0]?.textContent||'—')):'';
  for(const input of [name,material,mass]){input.disabled=busy||!fresh||!newMode;input.required=newMode}existing.disabled=busy||!fresh||newMode;ack.disabled=busy||!fresh;
  save.disabled=busy||!fresh||!ack.checked||(newMode?!(name.value.trim()&&material.value.trim()&&mass.value!==''&&mass.validity.valid):!existing.value);
  next.disabled=busy||!fresh||(newMode?!(name.value.trim()&&material.value.trim()&&mass.value!==''&&mass.validity.valid):!existing.value);back.disabled=busy;
  form.dataset.step=reviewing?'confirm':'spool';
  refreshButton.disabled=close.disabled=busy;for(const b of queue.querySelectorAll('button'))b.disabled=busy;
 }
 mode.onchange=existing.onchange=()=>{ack.checked=false;validate()};for(const input of [name,material,mass,ack])input.oninput=validate;
 form.onsubmit=e=>{e.preventDefault();if(save.disabled||!reviewing)return;run(async()=>{
  const payload={printer_id:preview.printer_id,channel:preview.channel,uid:preview.uid,expected_observation:preview.observation_revision,confirmed:true};
  if(mode.value==='new')Object.assign(payload,{name:name.value,material:material.value,remaining_g:mass.value});else{const c=preview.candidates.find(c=>c.spool_id===existing.value);Object.assign(payload,{spool_id:c.spool_id,expected_spool:c.revision})}
  if(request&&JSON.stringify(payload)!==request.intent)throw Error(t('Данные изменились после отправки. Проверьте снова.','Data changed after submission. Check again.'));
  if(!request)request={intent:JSON.stringify(payload),id:crypto.randomUUID()};
  await desktopCore('tag_register',{...payload,request_id:request.id});await refresh();
 })};
 dialog.addEventListener('cancel',e=>{if(busy)e.preventDefault()});
 const base=window.desktopInventoryLoaded;window.desktopInventoryLoaded=d=>{base(d);const count=d.observations.filter(r=>r.uid&&!r.spool).length;open.textContent='RFID / UID · '+count;language()};
 el('cal-read').addEventListener('click',e=>{e.preventDefault();e.stopImmediatePropagation();open.click()},true);
 // UID identity changes only through observed registration, never a text field.
 el('cal-uid').readOnly=true;el('cal-mode').disabled=true;language();validate();
})();
