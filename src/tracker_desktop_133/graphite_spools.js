// Spool dialogs follow the approved atlas; mutations keep the 2.0 API guards.
(()=>{
 const t=desktopText;
 const words={close:()=>t('Закрыть','Close','Schließen','Закрити','Cerrar'),cancel:()=>t('Отмена','Cancel','Abbrechen','Скасувати','Cancelar'),params:()=>t('Параметры катушки','Spool parameters','Spulenparameter','Параметри котушки','Parámetros de bobina'),color:()=>t('Цвет катушки','Spool color','Spulenfarbe','Колір котушки','Color de bobina'),balance:()=>t('Скорректировать остаток','Adjust balance','Restmenge korrigieren','Скоригувати залишок','Ajustar saldo')};
 const button=(text,fn,cls='')=>{const b=node('button',text,cls);b.type='button';b.onclick=fn;return b};
 const positions=s=>(s.assignments||[]).map(a=>a.printer_name+' / T'+a.channel).join(' · ');
 const context=s=>s.name+(positions(s)?' · '+positions(s):'');
 const newDialog=id=>{const d=node('dialog',undefined,'inventory-dialog graphite-spool-dialog');d.id=id;document.body.append(d);return d};
 function shell(d,title,subtitle){
  d.classList.add('graphite-spool-dialog');
  const header=node('header',undefined,'gs-header'),copy=node('div'),h=node('h2',title),sub=node('p',subtitle,'subtitle');
  h.id=d.id+'-title';d.setAttribute('aria-labelledby',h.id);copy.append(h,sub);
  const close=button('×',()=>d.close(),'gs-close dialog-close');close.setAttribute('aria-label',words.close());header.append(copy,close);
  const body=node('div',undefined,'gs-body'),footer=node('footer',undefined,'gs-footer');d.replaceChildren(header,body,footer);return {body,footer,sub};
 }
 const field=(text,input)=>{const label=node('label',undefined,'gs-field');label.append(node('span',text),input);return label};
 const pair=(...nodes)=>{const row=node('div',undefined,'gs-two');row.append(...nodes);return row};
 const open=d=>{for(const other of document.querySelectorAll('dialog[open]'))if(other!==d)other.close();d.showModal()};
 const footer=(d,host,save)=>host.append(button(words.cancel(),()=>d.close(),'gs-secondary'),save);
 const summary=s=>{const row=node('div',undefined,'gs-spool-summary'),copy=node('div');copy.append(node('strong',s.name),node('p',(s.material||'—')+' · '+displayGrams(s.remaining_g)+' '+gramUnit(),'subtitle'));row.append(window.trackerSpoolArt(s.color),copy);return row};
 const icons={params:'M4 7h16M4 17h16M8 4v6M16 14v6',balance:'M4 16l12-12 4 4L8 20H4z',transfer:'M4 7h16m-4-4 4 4-4 4M20 17H4m4-4-4 4 4 4',archive:'M3 3h18v5H3zM5 8v13h14V8M10 12h4',delete:'M3 6h18M9 6V3h6v3M6 6v15h12V6M10 10v7M14 10v7'};
 const icon=key=>{const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');svg.innerHTML='<path d="'+icons[key]+'" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>';return svg};
 const actions=newDialog('graphite-spool-actions'),adjust=newDialog('graphite-balance-dialog'),colors=newDialog('graphite-color-dialog');
 window.graphiteSpoolActions=(row,s,params)=>{
  const {body,footer:foot}=shell(actions,t('Действия с катушкой','Spool actions','Spulenaktionen','Дії з котушкою','Acciones de bobina'),context(s));foot.hidden=true;body.classList.add('gs-action-list');
  const action=(key,caption,fn)=>{const b=button('',()=>{actions.close();fn()},'gs-action');b.dataset.action=key;b.append(icon(key),node('span',caption));body.append(b)};
  action('params',t('Параметры','Parameters','Parameter','Параметри','Parámetros'),()=>params.click());
  if(!s.spoolman)action('balance',words.balance(),()=>balance(row.dataset.spoolId,s));
  const transfer=row.querySelector('[id^=desktop-transfer-]');if(transfer)action('transfer',t('Перенести между принтерами','Transfer between printers','Zwischen Druckern verschieben','Перенести між принтерами','Transferir entre impresoras'),()=>transfer.click());
  const archive=row.querySelector('.desktop-archive-action');if(archive)action('archive',archive.textContent,()=>archive.click());
  const remove=row.querySelector('.delete-spool');if(remove)action('delete',remove.textContent,()=>remove.click());
  open(actions);
 };
 function balance(id,s){
  const {body,footer:foot}=shell(adjust,words.balance(),context(s));
  const current=node('div',undefined,'gs-current-balance');current.append(node('small',t('Сейчас в Tracker','Current balance','Aktuell in Tracker','Зараз у Tracker','Saldo actual')),node('strong',displayGrams(s.remaining_g)+' '+gramUnit()));
  const input=node('input');input.id='graphite-balance-value';input.type='number';input.min='0';input.step='any';input.value=s.remaining_g;
  const ack=node('input');ack.type='checkbox';ack.id='graphite-balance-ack';const ackLabel=node('label',undefined,'gs-check');ackLabel.append(ack,node('span',t('Подтверждаю новое значение остатка.','I confirm the new balance.','Ich bestätige die neue Restmenge.','Підтверджую нове значення залишку.','Confirmo el nuevo saldo.')));
  body.append(current,field(t('Новый остаток, г','New balance, g','Neue Restmenge, g','Новий залишок, г','Nuevo saldo, g'),input),node('p',t('Для расхода конкретного задания используйте ручной учёт в истории: там сохраняется защита от повторного списания.','For a particular job, use manual accounting in History to retain protection against duplicate deductions.','Für einen bestimmten Auftrag die manuelle Erfassung im Verlauf verwenden, damit keine doppelten Abbuchungen entstehen.','Для витрат конкретного завдання використовуйте ручний облік в історії із захистом від повторного списання.','Para un trabajo concreto, use el registro manual del historial para evitar descuentos duplicados.'),'gs-notice'),ackLabel);
  let busy=false;
  const save=button(t('Установить остаток','Set balance','Restmenge setzen','Встановити залишок','Establecer saldo'),()=>act(async()=>{if(busy||!ack.checked||!input.reportValidity())return;busy=true;save.disabled=true;try{await api('/api/spools/update',{id,remaining_g:input.value});adjust.close();await loadData()}finally{busy=false;validate()}}),'gs-primary');save.id='graphite-balance-save';
  const validate=()=>save.disabled=busy||!ack.checked||input.value===''||!input.checkValidity();input.oninput=ack.onchange=validate;validate();footer(adjust,foot,save);open(adjust);input.focus();
 }
 function color(id,s){
  const {body,footer:foot}=shell(colors,words.color(),context(s));body.append(summary(s));let selected=s.color||'',busy=false;
  const palette=node('div',undefined,'gs-palette'),value=node('code',selected||'—');palette.setAttribute('role','group');palette.setAttribute('aria-label',words.color());
  function select(c){selected=c;value.textContent=c||'—';for(const b of palette.children)b.setAttribute('aria-pressed',String(b.dataset.color===c))}
  for(const c of PALETTE){const swatch=button('',()=>select(c),'gs-swatch');swatch.style.backgroundColor=c;swatch.dataset.color=c;swatch.setAttribute('aria-label',c);palette.append(swatch)}select(selected);
  const clear=button(t('Убрать цвет','Clear color','Farbe entfernen','Прибрати колір','Quitar color'),()=>select(''),'gs-secondary');body.append(palette,pair(value,clear));
  const save=button(t('Сохранить цвет','Save color','Farbe speichern','Зберегти колір','Guardar color'),()=>act(async()=>{if(busy)return;busy=true;save.disabled=true;try{await api('/api/spools/color',{id,color:selected});colors.close();await loadData()}finally{busy=false;save.disabled=false}}),'gs-primary');save.id='graphite-color-save';footer(colors,foot,save);open(colors);
 }
 // Rebuild only the presentation around the original calibration form.
 const params=el('inventory-param-dialog'),form=el('cal-form'),save=el('cal-save'),oldTitle=el('cal-title'),help=el('cal-help');
 const hidden=node('div');hidden.hidden=true;hidden.append(el('cal-spool'),el('cal-mode'),el('cal-uid'),oldTitle,help,el('cal-read'),el('cal-tags'));
 const diameter=el('cal-diameter'),density=el('cal-density');hidden.append(diameter,density,save);form.replaceChildren(hidden);save.setAttribute('form','cal-form');
 window.inventoryParameters=id=>{
  el('cal-spool').value=id;el('cal-spool').onchange?.();const s=desktopFormData.spools[id];if(!s)return;
  const {body,footer:foot}=shell(params,words.params(),context(s));body.append(form);
  const info=summary(s),badge=node('span',s.uid?'RFID':t('Без метки','No tag','Ohne Tag','Без мітки','Sin etiqueta'),'gs-badge');info.append(badge);
  if(!s.spoolman)info.append(button(t('Цвет','Color','Farbe','Колір','Color'),()=>color(id,s),'gs-secondary gs-edit-color'));
  const tag=node('div',undefined,'gs-tag'),copy=node('div');copy.append(node('h3',t('Метка катушки','Spool tag','Spulen-Tag','Мітка котушки','Etiqueta de bobina')),node(s.uid?'code':'span',s.uid||t('Метка не привязана','No tag attached','Kein Tag verknüpft','Мітку не прив’язано','Sin etiqueta vinculada')));
  tag.append(copy,button('RFID / UID',()=>{params.close();el('desktop-tags-open').click()},'gs-secondary'));
  form.replaceChildren(hidden,info,pair(field(t('Диаметр, мм','Diameter, mm','Durchmesser, mm','Діаметр, мм','Diámetro, mm'),diameter),field(t('Плотность, г/см³','Density, g/cm³','Dichte, g/cm³','Густина, г/см³','Densidad, g/cm³'),density)),tag,node('p',t('Расход по движению — расчётная оценка, а не измерение весами.','Motion-based usage is an estimate, not a scale measurement.','Bewegungsbasierter Verbrauch ist eine Schätzung, keine Waagenmessung.','Витрата за рухом — розрахункова оцінка, а не вимірювання вагами.','El consumo por movimiento es una estimación, no una medición con báscula.'),'subtitle'));
  footer(params,foot,save);save.classList.add('gs-primary');open(params);diameter.focus();
 };
 // Called from the existing transfer handler, retaining its request/retry closure.
 window.graphiteTransferDialog=(d,s,source,target,head,apply)=>{
  const {body,footer:foot}=shell(d,t('Перенести катушку','Transfer spool','Spule verschieben','Перенести котушку','Transferir bobina'),s.name+' · '+(s.material||'—')+' · '+displayGrams(s.remaining_g)+' '+gramUnit());
  const route=node('div',undefined,'gs-route'),from=node('div'),to=node('div'),dest=node('strong'),destHead=node('p',undefined,'subtitle');
  from.append(node('small',t('Откуда','From','Von','Звідки','Desde')),node('strong',source),node('p','T'+d.dataset.sourceChannel,'subtitle'));
  to.append(node('small',t('Куда','To','Nach','Куди','Hacia')),dest,destHead);route.append(from,node('span','→','gs-route-arrow'),to);
  const update=()=>{dest.textContent=target.selectedOptions[0]?.textContent||'—';destHead.textContent='T'+head.value};target.addEventListener('change',update);head.addEventListener('change',update);update();
  body.append(route,pair(field(t('Принтер назначения','Destination printer','Zieldrucker','Принтер призначення','Impresora de destino'),target),field(t('Головка назначения','Destination toolhead','Zieldruckkopf','Голівка призначення','Cabezal de destino'),head)),node('p',t('Подтверждение означает, что катушка уже физически перенесена. Остаток не меняется.','Confirm only after physically moving the spool. The balance stays unchanged.','Erst nach dem physischen Umsetzen bestätigen. Die Restmenge bleibt unverändert.','Підтверджуйте після фізичного перенесення котушки. Залишок не змінюється.','Confirme después de mover físicamente la bobina. El saldo no cambia.'),'gs-notice'));
  apply.classList.add('gs-primary');footer(d,foot,apply);
 };
})();
