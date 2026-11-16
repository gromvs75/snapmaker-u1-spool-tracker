// Full 1.3.3 Spoolman tab, backed only by the 2.0 durable delivery queue.
(()=>{
 const t=desktopText,dialog=node('dialog');dialog.id='desktop-delivery-dialog';dialog.className='inventory-dialog';document.body.append(dialog);
 let busy=false,decisionRequest=null;
 const caption=state=>({held:t('Нужна проверка перед отправкой','Review before sending','Vor Versand prüfen','Перевірити перед надсиланням','Revisar antes de enviar'),pending:t('Отправка разрешена','Sending approved','Versand freigegeben','Надсилання дозволено','Envío autorizado'),sending:t('Отправляется','Sending','Wird gesendet','Надсилається','Enviando'),uncertain:t('Результат неизвестен — нужна сверка','Outcome unknown — reconcile','Ergebnis unbekannt — abgleichen','Результат невідомий — потрібна звірка','Resultado desconocido — conciliar'),sent:t('Подтверждено','Confirmed','Bestätigt','Підтверджено','Confirmado'),resolved:t('Закрыто без отправки','Closed without sending','Ohne Versand geschlossen','Закрито без надсилання','Cerrado sin enviar')})[state]||state;
 const button=(text,id,fn)=>{const b=node('button',text);b.type='button';b.id=id;b.onclick=fn;return b};
 window.desktopDeliveryRows=data=>{
  const root=el('sm-queue');root.replaceChildren();
  if(!data.delivery.length)root.textContent=t('Операций пока нет','No operations yet','Noch keine Vorgänge','Операцій ще немає','Todavía no hay operaciones');
  for(const row of [...data.delivery].reverse()){
   const box=node('div');box.style.cssText='border-bottom:1px solid var(--border);padding:12px 0';box.dataset.operation=row.operation_id;
   box.append(node('strong',(desktopFormData?.spools[row.spool_id]?.name||'#'+row.remote_id)+' · '+displayGrams(row.delta_mg/1000)+' g'),node('p',caption(row.state)));
   box.append(button(t('Просмотр и сверка','View and reconcile','Anzeigen und abgleichen','Перегляд і звірка','Ver y conciliar'),'',()=>open(row,data)));root.append(box);
  }
 };
 function open(row,data){
  if(busy)return;decisionRequest=null;dialog.replaceChildren();dialog.showModal();
  const close=button(t('Закрыть','Close','Schließen','Закрити','Cerrar'),'desktop-delivery-close',()=>dialog.close());
  const note=node('textarea'),ack=node('input'),ackLabel=node('label'),message=node('p'),evidence=node('div'),actions=node('div');note.id='desktop-delivery-note';note.maxLength=1000;note.rows=3;ack.type='checkbox';ack.id='desktop-delivery-ack';message.id='desktop-delivery-message';message.setAttribute('role','status');
  note.style.cssText='display:block;width:100%;box-sizing:border-box;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:12px;font:inherit;resize:vertical';
  ackLabel.style.cssText='display:flex;align-items:flex-start;gap:10px;margin:18px 0';ack.style.cssText='flex:none;width:18px;height:18px;margin:0';actions.style.cssText='display:flex;gap:10px;flex-wrap:wrap';
  ackLabel.append(ack,document.createTextNode(t('Я проверил(а) операцию и подтверждаю решение.','I reviewed this operation and confirm my decision.','Vorgang geprüft, Entscheidung bestätigt.','Я перевірив(ла) операцію та підтверджую рішення.','He revisado la operación y confirmo la decisión.')));
  dialog.append(close,node('h2',caption(row.state)),node('p',row.url+' · #'+row.remote_id+' · '+displayGrams(row.delta_mg/1000)+' g'),node('p',t('Остаток сервера сам по себе не доказывает, была ли отправка применена. Неизвестные операции автоматически не повторяются.','Server balance alone does not prove whether a write was applied. Unknown operations never retry automatically.','Der Serverrest allein beweist keine Buchung. Unklare Vorgänge werden nie automatisch wiederholt.','Залишок сервера сам по собі не доводить списання. Невідомі операції автоматично не повторюються.','El saldo del servidor no demuestra por sí solo si se aplicó el envío. Las operaciones inciertas nunca se repiten automáticamente.')));
  const review=button(t('Прочитать Spoolman и журнал','Read Spoolman and audit','Spoolman und Protokoll lesen','Прочитати Spoolman і журнал','Leer Spoolman y registro'),'desktop-delivery-review',()=>work(async()=>{const r=await desktopCore('delivery_review',{operation_id:row.operation_id,expected_revision:row.revision});evidence.replaceChildren(node('p',(r.remote.name||'')+' · '+(r.remote.remaining_g===null?'—':displayGrams(r.remote.remaining_g)+' g')));for(const entry of r.audit)evidence.append(node('p',caption(entry.previous)+' → '+caption(entry.state)+' · '+entry.note));}));
  dialog.append(review,evidence,node('p',t('Основание решения','Reason for the decision','Begründung','Підстава рішення','Motivo de la decisión')),note,ackLabel,actions,message);
  async function work(fn){if(busy)return;busy=true;for(const b of dialog.querySelectorAll('button'))b.disabled=true;try{await fn()}catch(e){message.textContent=e.message}finally{busy=false;for(const b of dialog.querySelectorAll('button'))b.disabled=false}}
  const choices=row.state==='held'?[['approve',t('Разрешить отправку','Approve sending','Versand freigeben','Дозволити надсилання','Autorizar envío')],['cancel',t('Закрыть без отправки','Close without sending','Ohne Versand schließen','Закрити без надсилання','Cerrar sin enviar')]]:row.state==='uncertain'?[['applied',t('Уже учтено в Spoolman','Already applied in Spoolman','In Spoolman bereits gebucht','Уже враховано у Spoolman','Ya aplicado en Spoolman')],['not_applied',t('Не учтено — разрешить новую попытку','Not applied — approve a new attempt','Nicht gebucht — neuen Versuch freigeben','Не враховано — дозволити нову спробу','No aplicado — autorizar otro intento')],['cancel',t('Закрыть без отправки','Close without sending','Ohne Versand schließen','Закрити без надсилання','Cerrar sin enviar')]]:[];
  for(const [decision,label] of choices)actions.append(button(label,'desktop-delivery-'+decision,()=>work(async()=>{
   if(!ack.checked||!note.value.trim())throw Error(t('Укажите основание и подтвердите решение.','Enter a reason and confirm the decision.','Begründung eingeben und bestätigen.','Укажіть підставу та підтвердьте рішення.','Indique un motivo y confirme la decisión.'));
   const intent={operation_id:row.operation_id,expected_revision:row.revision,decision,note:note.value,confirmed:true};
   if(decisionRequest&&decisionRequest.intent!==JSON.stringify(intent))throw Error(t('Решение изменилось после отправки. Откройте операцию снова.','Decision changed after submission. Reopen the operation.'));
   if(!decisionRequest)decisionRequest={intent:JSON.stringify(intent),id:crypto.randomUUID()};
   await desktopCore('delivery_decide',{...intent,request_id:decisionRequest.id});dialog.close();await window.refreshSpoolmanAfterRestore();
  })));
  if(row.state==='pending')actions.append(button(t('Отправить сейчас','Send now','Jetzt senden','Надіслати зараз','Enviar ahora'),'desktop-delivery-send',()=>work(async()=>{
   if(data.state.mode!=='send')throw Error(t('Включите разрешение отправки в настройках Spoolman.','Enable sending in Spoolman settings.'));
   if(!ack.checked)throw Error(t('Подтвердите отправку.','Confirm sending.','Versand bestätigen.','Підтвердьте надсилання.','Confirme el envío.'));
   const result=await desktopCore('delivery_send',{operation_id:row.operation_id,expected_revision:row.revision,confirmed:true});message.textContent=caption(result.status);await window.refreshSpoolmanAfterRestore();
   // Reopen to bind subsequent actions to the new state/revision.
   const next=desktopSpoolmanData.delivery.find(r=>r.operation_id===row.operation_id);busy=false;if(next)open(next,desktopSpoolmanData);
  })));
 }
 dialog.addEventListener('cancel',e=>{if(busy)e.preventDefault()});
})();
