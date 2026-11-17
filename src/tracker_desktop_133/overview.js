// Approved overview grouping: telemetry, actionable check, and independent slice.
// Presentation only; original guard actions and accounting routes are retained.
(()=>{
 const t=desktopText,card=document.querySelector('.overview-card');
 const badge=el('overview-connection');el('overview-result').after(badge);el('overview-result').hidden=true;
 const style=node('style');style.textContent=`
 .overview-card,#slice-forecast{padding:24px!important;border-radius:14px;border-color:var(--border)!important}
 .overview-card #overview-title,#slice-forecast #forecast-heading{font-size:11px;letter-spacing:1.4px;margin:0;color:#a4b0c4}
 .overview-card .overview-heading>div{width:100%;min-width:0}
 .overview-card #overview-connection{display:block;width:fit-content;max-width:100%;padding:0;margin:9px 0 0;background:none;font-size:24px;line-height:1.25;font-weight:650;white-space:normal;letter-spacing:-.45px}
 .overview-card #overview-connection.is-connected{color:#7fe1af;background:none}
 .overview-card[data-state=paused] #overview-connection,.overview-card[data-state=error] #overview-connection{color:#f1c876}
 .overview-card #overview-file{margin:6px 0 0;font-size:14px;overflow-wrap:anywhere}
 #guard-content:empty{display:none}
 #guard-content{margin-top:20px}
 .desktop-check{padding:14px 16px;background:#302a20;border-left:3px solid #f1c876;border-radius:9px;color:#f6dca5}
 .desktop-check.is-ok{background:transparent;border-left-color:#7fe1af;color:var(--text)}
 .desktop-check strong{font-size:14px;font-weight:600}
 .desktop-check p{font-size:13px;margin:4px 0 0;color:#dfcaa6}
 .desktop-check.is-ok p{color:#a4b0c4}
 .desktop-check details{margin-top:8px}
 .desktop-check details p{overflow-wrap:anywhere}
 .desktop-check summary,#desktop-forecast-details summary{width:fit-content;font-size:12px;cursor:pointer}
 .desktop-check ol{padding-left:18px;font-size:13px;line-height:1.65}
 .desktop-check .form-inline{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px}
 .desktop-check button{padding:8px 12px;font-size:13px;margin:0}
 .desktop-check table{font-size:12px;table-layout:fixed;width:100%;margin-top:12px}
 .desktop-check th,.desktop-check td{padding:8px 5px;overflow-wrap:anywhere;color:var(--text)}
 #slice-forecast .overview-heading{flex-wrap:wrap}
 #desktop-forecast-separate{font-size:11px;background:#242e40;border-radius:5px;padding:4px 7px;color:#bdc7d8}
 #slice-forecast #forecast-status{font-size:21px;line-height:1.3;margin:16px 0 12px;font-weight:650;letter-spacing:-.3px}
 #slice-forecast .forecast-meta{font-size:13px;gap:7px 18px;color:#c3cddd}
 #slice-forecast #forecast-time{font-size:13px}
 #desktop-forecast-assumption{font-size:12px;color:#a4b0c4;margin:8px 0 0}
 #desktop-forecast-footer{display:flex;gap:8px 18px;flex-wrap:wrap;border-top:1px solid var(--border);margin-top:18px;padding-top:14px;font-size:12px;color:#a4b0c4}
 #desktop-forecast-details{margin-top:14px;color:#b8c9e1}
 #desktop-forecast-details p{font-size:12px;margin:10px 0;overflow-wrap:anywhere}
 #desktop-forecast-details #forecast-hide{margin-top:8px;font-size:12px}
 #desktop-forecast-source-label{font-size:13px}
 @media(max-width:700px){.overview-card,#slice-forecast{padding:18px!important}.overview-card #overview-connection{font-size:22px}}
 `;document.body.append(style);
 const overview=renderOverview;
 renderOverview=data=>{overview(data);card.dataset.state=data.monitor.state;
  el('overview-title').textContent=t('Текущая печать','Current print','Aktueller Druck','Поточний друк','Impresión actual');
  // The main heading is live telemetry. A historical start check stays below.
  el('overview-file').textContent=data.monitor.connected?data.monitor.filename||'':data.last_preflight?.filename?t('Последнее задание: ','Last job: ','Letzter Auftrag: ','Останнє завдання: ','Último trabajo: ')+data.last_preflight.filename:'';
 };
 const reason=value=>String(value||'')
  .replaceAll('assignment/balance unconfirmed',t('назначение катушки или остаток не подтверждены','spool assignment or balance is unconfirmed','Spulenzuordnung oder Restmenge unbestätigt','призначення котушки або залишок не підтверджені','asignación de bobina o saldo sin confirmar'))
  .replaceAll('insufficient material including reserve',t('материала не хватает с учётом резерва','not enough material including reserve','Material einschließlich Reserve reicht nicht','матеріалу не вистачає з урахуванням резерву','material insuficiente con la reserva'))
  .replaceAll('Material mismatch: advisory only; check spool type',t('Материал не совпадает: проверьте тип катушки','Material mismatch: check spool type','Materialabweichung: Spulentyp prüfen','Матеріал не збігається: перевірте тип котушки','Material distinto: compruebe el tipo de bobina'))
  .replaceAll('late observation: pause not requested',t('Наблюдение началось позже старта; пауза не запрашивалась','Observation began after start; no pause requested','Beobachtung nach Druckbeginn; keine Pause angefordert','Спостереження почалось після старту; пауза не запитувалась','Observación posterior al inicio; no se solicitó pausa'));
 const originalGuard=renderGuard;let signature='';
 renderGuard=(data,force=false)=>{
  const g=data.last_guard||data.last_preflight,m=data.monitor;
  const next=JSON.stringify([g,m.state,m.connected,m.filename,currentLang]);if(!force&&next===signature)return;signature=next;
  const content=el('guard-content'),open=content.querySelector('details')?.open;
  originalGuard(data,true);const actions=content.querySelector('.form-inline');content.replaceChildren();if(!g)return;
  const stateText=guardText[currentLang]||guardText.en;
  const warn=g.state&&g.state!=='ok',box=node('div',undefined,'desktop-check'+(warn?'':' is-ok'));
  const same=m.connected&&m.filename===g.filename;
  const rows=(g.rows||[]).filter(r=>['unassigned','insufficient'].includes(r.status));
  const main=rows.map(r=>reason(r.tool+': '+(r.status==='unassigned'?'assignment/balance unconfirmed':'insufficient material including reserve'))).join(' · ');
  box.append(node('strong',warn?(main||stateText[g.state]||t('Проверка запуска требует внимания','Start check needs attention','Startprüfung erfordert Aufmerksamkeit','Перевірка запуску потребує уваги','La comprobación de inicio requiere atención')):t('Проверка запуска выполнена','Start check performed','Startprüfung durchgeführt','Перевірку запуску виконано','Comprobación de inicio realizada')));
  box.append(node('p',!same?(m.connected&&m.filename?t('Последняя проверка: ','Last check: ','Letzte Prüfung: ','Остання перевірка: ','Última comprobación: ')+g.filename:t('Последняя сохранённая проверка запуска.','Last saved start check.','Letzte gespeicherte Startprüfung.','Остання збережена перевірка запуску.','Última comprobación de inicio guardada.')):
   g.state==='warning'&&m.state==='printing'?t('Печать продолжается. Для учёта расхода нужна проверка.','Printing continues. Usage accounting needs review.','Druck läuft weiter. Verbrauchserfassung muss geprüft werden.','Друк триває. Для обліку витрат потрібна перевірка.','La impresión continúa. Revise el registro de consumo.'):(stateText[g.state]||g.summary||'')));
  const details=node('details');details.id='desktop-check-details';details.open=!!open;
  details.append(node('summary',warn?t('Что проверить','What to check','Was prüfen','Що перевірити','Qué comprobar'):t('Подробности проверки','Check details','Prüfdetails','Подробиці перевірки','Detalles de comprobación')));
  if(rows.some(r=>r.status==='unassigned'))details.append(node('p',t('В «Катушки → Головки T0–T3» проверьте назначение и остаток катушки. Подтвердите назначение, когда действие доступно.','In Spools → Heads T0–T3, check the assigned spool and balance. Confirm the assignment when available.','Unter Spulen → Köpfe T0–T3 Zuordnung und Restmenge prüfen. Zuordnung bestätigen, sobald verfügbar.','У «Котушки → Головки T0–T3» перевірте призначення й залишок. Підтвердьте призначення, коли дія доступна.','En Bobinas → Cabezales T0–T3, revise la asignación y el saldo. Confirme la asignación cuando esté disponible.')));
  if(g.reason)details.append(node('p',reason(g.reason)));
  if(g.time)details.append(node('p',new Date(g.time).toLocaleString(currentLang)));
  if(g.rows?.length){const table=node('table'),head=node('tr');
   for(const title of [t('Головка','Head','Kopf','Головка','Cabezal'),t('Катушка','Spool','Spule','Котушка','Bobina'),t('Нужно','Needed','Benötigt','Потрібно','Necesario'),t('Остаток','Remaining','Rest','Залишок','Restante')])head.append(node('th',title));table.append(head);
   for(const r of g.rows){const row=node('tr');for(const value of [r.tool,r.spool_name||'—',displayGrams(r.required_g)+' '+gramUnit(),r.remaining_g==null?'—':displayGrams(r.remaining_g)+' '+gramUnit()])row.append(node('td',value));table.append(row)}details.append(table);
  }
  box.append(details);if(actions)box.append(actions);
  const ongoing=same&&['printing','paused'].includes(m.state);
  if(!ongoing&&!actions){
   const past=node('details');past.id='desktop-past-check';
   past.append(node('summary',t('Проверка при старте — сохранённый результат','Start check — saved result','Startprüfung — gespeichertes Ergebnis','Перевірка на старті — збережений результат','Comprobación inicial — resultado guardado')));
   box.classList.add('is-ok');
   box.querySelector('p').textContent=t('Данные на момент запуска задания. Изменение остатка не пересчитывает эту проверку.','Data recorded at job start. Adjusting the balance does not recalculate this check.','Daten beim Auftragsstart. Eine Restmengenkorrektur berechnet diese Prüfung nicht neu.','Дані на момент старту завдання. Зміна залишку не перераховує цю перевірку.','Datos del inicio del trabajo. Ajustar el saldo no recalcula esta comprobación.');
   past.append(box);content.append(past);
  }else content.append(box);
 };
 const forecast=el('slice-forecast'),header=forecast.querySelector('.overview-heading'),meta=forecast.querySelector('.forecast-meta');
 const separate=node('span');separate.id='desktop-forecast-separate';header.append(separate);
 const sourceLabel=node('span','Snorca');sourceLabel.id='desktop-forecast-source-label';el('forecast-time').before(sourceLabel);
 const assumption=node('p');assumption.id='desktop-forecast-assumption';meta.after(assumption);
 const footer=node('div');footer.id='desktop-forecast-footer';const oldFoot=el('forecast-reserve').parentElement;footer.append(el('forecast-reserve'),el('forecast-no-debit'));oldFoot.replaceWith(footer);
 const details=node('details');details.id='desktop-forecast-details';const summary=node('summary');details.append(summary);footer.after(details);
 const exact=node('p');exact.id='desktop-forecast-exact-time';details.append(exact,el('desktop-forecast-source'),el('desktop-forecast-provisional'),forecast.querySelector('.forecast-mapping'),el('forecast-hide'));
 window.desktopForecastGrouped=(entry,state)=>{
  el('forecast-heading').textContent=t('Прогноз нарезки','Slice forecast','Slicing-Prognose','Прогноз нарізки','Previsión del laminado');
  separate.textContent=t('Отдельно от текущей печати','Separate from the current print','Getrennt vom aktuellen Druck','Окремо від поточного друку','Independiente de la impresión actual');
  separate.hidden=!entry;sourceLabel.hidden=!entry;footer.hidden=!entry;details.hidden=false;forecast.querySelector('.forecast-mapping').hidden=!entry;exact.hidden=!entry;
  assumption.hidden=!entry;assumption.textContent=t('По сохранённым остаткам. Привязка материалов к головкам предполагается.','Based on saved balances. Material-to-head mapping is assumed.','Auf Basis gespeicherter Restmengen. Material-Kopf-Zuordnung angenommen.','За збереженими залишками. Прив’язка матеріалів до головок припускається.','Según saldos guardados. Se presupone la asignación de materiales a cabezales.');
  summary.textContent=t('Источник и подробности расчёта','Source and calculation details','Quelle und Berechnungsdetails','Джерело та подробиці розрахунку','Origen y detalles del cálculo');
  el('forecast-no-debit').textContent=t('Прогноз не списывает расход','Forecast does not deduct usage','Prognose bucht keinen Verbrauch','Прогноз не списує витрати','La previsión no descuenta consumo');
  if(!entry)summary.textContent=t('Дополнительно','More','Weitere Optionen','Додатково','Más opciones');
  if(entry){exact.textContent=new Date(entry.observed_at*1000).toLocaleString(currentLang);el('forecast-time').textContent=new Date(entry.observed_at*1000).toLocaleString(currentLang,{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
   el('forecast-status').textContent=entry.unknown?t('Назначение или остаток не подтверждены','Assignment or balance unconfirmed','Zuordnung oder Restmenge unbestätigt','Призначення або залишок не підтверджені','Asignación o saldo sin confirmar'):entry.shortage?t('Материала не хватает','Not enough material','Material reicht nicht aus','Матеріалу не вистачає','Material insuficiente'):t('✓ По расчёту материала хватит','✓ Estimated material is sufficient','✓ Material reicht laut Berechnung','✓ За розрахунком матеріалу вистачить','✓ El material será suficiente según el cálculo');
  }else el('forecast-status').textContent=t('Ожидаем нарезку Snorca','Waiting for a Snorca slice','Warte auf Snorca-Slicing','Очікуємо нарізку Snorca','Esperando el laminado de Snorca');
 };
})();
