"""Compact name comparison using the Tracker visual system."""
PANEL = r'''
<style>
#sc-dialog{box-sizing:border-box;width:min(860px,calc(100vw - 32px));max-height:calc(100dvh - 32px);padding:24px;border:1px solid var(--border);border-radius:14px;background:var(--card);color:var(--text);font:inherit;font-size:14px;line-height:1.5}
#sc-dialog::backdrop{background:#0009}#sc-dialog *{box-sizing:border-box}#sc-dialog [hidden]{display:none!important}
.sc-header{display:flex;align-items:center;justify-content:space-between;gap:16px}#sc-dialog h2{margin:0;font-size:20px;color:var(--text);letter-spacing:0;text-transform:none}#sc-dialog p{line-height:1.6}.sc-intro{color:var(--muted);margin:12px 0 20px}
.sc-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.3fr);gap:24px}.sc-picker{min-width:0}#sc-search{width:100%;margin:8px 0}.sc-tabs{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}#sc-dialog .sc-tab{padding:6px 10px;font-size:12px;background:#222c3e;color:var(--text)}#sc-dialog .sc-tab[aria-pressed=true]{background:#1d2a44;color:#9cc4ff;outline:1px solid #6aa8ff}
#sc-source-list{max-height:300px;overflow:auto;display:grid;gap:6px}#sc-dialog .sc-source-item{display:flex;align-items:center;gap:10px;width:100%;text-align:left;background:var(--bg);border:1px solid var(--border);padding:10px;color:var(--text);border-radius:8px;white-space:normal;overflow-wrap:anywhere}#sc-dialog .sc-source-item[aria-pressed=true]{border-color:#6aa8ff;background:#1d2a44}.sc-label{flex:1;min-width:0}.sc-label small{display:block;color:var(--muted);font-size:12px}.sc-dot{width:13px;height:13px;border:1px solid #94a3b8;border-radius:50%;flex:none}
.sc-editor{min-width:0;border-left:1px solid var(--border);padding-left:24px}.sc-column{padding:14px;background:var(--bg);border:1px solid var(--border);border-radius:10px;margin-bottom:12px}.sc-column h3{font-size:12px;color:var(--muted);margin:0 0 8px;font-weight:500}.sc-column p{margin:0;overflow-wrap:anywhere;font-size:15px}#sc-sync{width:100%;min-height:44px}#sc-message{min-height:44px;color:var(--muted);margin:12px 0}#sc-message[data-error=true]{color:#ffab91}.sc-footer{border-top:1px solid var(--border);padding-top:16px;margin-top:20px;display:flex;gap:12px;align-items:center;justify-content:space-between}.sc-footer p{margin:0;color:var(--muted);font-size:12px;max-width:510px}#sc-dialog .sc-secondary{background:#222c3e;color:var(--text)}.sc-empty{color:var(--muted);padding:12px 0}.sc-open{margin:0 0 12px!important;font-size:13px!important}#sc-dialog button:focus-visible,#sc-dialog input:focus-visible{outline:2px solid #66d0ff;outline-offset:2px}
@media(max-width:620px){#sc-dialog{padding:18px}.sc-layout{grid-template-columns:1fr;gap:18px}.sc-editor{border-left:0;padding-left:0}#sc-source-list{max-height:160px}.sc-footer{align-items:stretch;flex-direction:column}.sc-header{align-items:flex-start}#sc-dialog h2{font-size:18px}}
#sc-sync:disabled{background:#222c3e;color:var(--muted);cursor:default}
</style>
<dialog id="sc-dialog" aria-labelledby="sc-title" aria-describedby="sc-intro">
 <div class="sc-header"><h2 id="sc-title" data-sc-text="title"></h2><button id="sc-close" class="sc-secondary" data-sc-text="close"></button></div>
 <p id="sc-intro" class="sc-intro" data-sc-text="intro"></p>
 <div class="sc-layout">
  <section class="sc-picker"><label for="sc-search" data-sc-text="search"></label><input type="search" id="sc-search" autocomplete="off">
   <div class="sc-tabs" role="group" aria-label="Filter">
    <button class="sc-tab" data-sc-filter="all" aria-pressed="true" data-sc-text="all"></button>
    <button class="sc-tab" data-sc-filter="different" aria-pressed="false" data-sc-text="different"></button>
    <button class="sc-tab" data-sc-filter="same" aria-pressed="false" data-sc-text="same"></button>
    <button class="sc-tab" data-sc-filter="local" aria-pressed="false" data-sc-text="local"></button>
   </div><div id="sc-source-list"></div>
  </section>
  <section class="sc-editor" aria-label="Tracker / Spoolman">
   <div class="sc-column"><h3 data-sc-text="tracker"></h3><p id="sc-tracker-name">—</p></div>
   <div class="sc-column"><h3 data-sc-text="canonical"></h3><p id="sc-canonical-name">—</p></div>
   <button id="sc-sync" disabled data-sc-text="sync"></button>
   <p id="sc-message" role="status" aria-live="polite"></p>
   <button id="sc-refresh" class="sc-secondary" data-sc-text="refresh"></button>
  </section>
 </div>
 <div class="sc-footer"><p data-sc-text="separate"></p><button id="sc-settings" class="sc-secondary" data-sc-text="settings"></button></div>
</dialog>
'''
SCRIPT = r'''
<script>
(() => {
 const $=id=>document.getElementById('sc-'+id),dialog=$('dialog');
 const words={ru:{title:'Названия катушек Spoolman',close:'Закрыть',intro:'Обновление названий уже связанных катушек. Остатки и история не меняются.',search:'Найти катушку',all:'Все',different:'Различия',same:'Совпадают',local:'Локальные',tracker:'Название в Tracker',canonical:'Название в Spoolman',sync:'Обновить название в Tracker',synced:'Название совпадает',only:'Изменится только название в Tracker.',matched:'Названия совпадают — обновление не требуется.',choose:'Выберите катушку из списка.',localHelp:'Эта катушка создана в Tracker и не связана со Spoolman. Обновление названия недоступно.',separate:'Создание катушки в обеих программах даёт две отдельные записи. Здесь они не объединяются. Назначить катушку Spoolman на T0–T3 можно в настройках.',settings:'Настройки Spoolman',refresh:'Обновить каталог',unavailable:'Данные Spoolman недоступны или устарели. Обновите каталог.',empty:'Катушки не найдены',loading:'Загрузка…',syncing:'Обновление…',success:'Название обновлено. Остатки и история сохранены.',error:'Не удалось загрузить сравнение.',open:'Проверить названия',difference:'Различие'},en:{title:'Spoolman spool names',close:'Close',intro:'Update names of already linked spools. Balances and history stay unchanged.',search:'Find a spool',all:'All',different:'Different',same:'Matching',local:'Local',tracker:'Name in Tracker',canonical:'Name in Spoolman',sync:'Update name in Tracker',synced:'Name is up to date',only:'Only the name in Tracker will change.',matched:'Names match — no update needed.',choose:'Select a spool from the list.',localHelp:'This spool was created in Tracker and is not linked to Spoolman. Name updates are unavailable.',separate:'Creating a spool in both apps makes two separate records. This screen does not merge them. Assign a Spoolman spool to T0–T3 in settings.',settings:'Spoolman settings',refresh:'Refresh catalog',unavailable:'Spoolman data is unavailable or stale. Refresh the catalog.',empty:'No spools found',loading:'Loading…',syncing:'Updating…',success:'Name updated. Balances and history preserved.',error:'Could not load comparison.',open:'Check names',difference:'Different'}};
 const t=k=>(words[currentLang]||words.en)[k];
 let inventory=null,comparison=null,selected=null,filter='all',busy=false,loading=false;
 const shortName=n=>(n||'').replace(/^\[Spoolman #\d+\]\s*/,'');
 const rowFor=id=>comparison?.rows.find(r=>r.id===id);
 function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
 function message(text,error=false){$('message').textContent=text;$('message').dataset.error=String(error);}
 async function request(action,body){const r=await fetch('/api/spoolman/'+action,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error(d.error||t('error'));return d;}
 function controls(){$('source-list').querySelectorAll('button').forEach(b=>b.disabled=busy||loading);const row=rowFor(selected);$('sync').disabled=busy||loading||!row?.available||row.matches;$('sync').textContent=t(busy?'syncing':row?.matches?'synced':'sync');$('refresh').disabled=busy||loading;}
 function render(){
  dialog.querySelectorAll('[data-sc-text]').forEach(e=>e.textContent=t(e.dataset.scText));
  const terms=$('search').value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const visible=Object.entries(inventory?.spools||{}).filter(([id,s])=>{
   const r=rowFor(id),filterOK=filter==='all'||(filter==='local'?!s.spoolman:filter==='same'?r?.matches:r&&!r.matches);
   const text=[s.name,s.material,s.spoolman?.id,r?.manufacturer,r?.canonical_name].join(' ').toLocaleLowerCase();
   return filterOK&&terms.every(term=>text.includes(term));
  });
  if(!visible.some(([id])=>id===selected))selected=visible[0]?.[0]||null;
  $('source-list').replaceChildren();
  for(const [id,s] of visible){const b=node('button',undefined,'sc-source-item');b.type='button';b.setAttribute('aria-pressed',String(selected===id));b.disabled=busy||loading;b.onclick=()=>{selected=id;render();};const dot=node('span',undefined,'sc-dot');if(/^#[0-9a-f]{6}$/i.test(s.color||''))dot.style.backgroundColor=s.color;dot.setAttribute('aria-hidden','true');const label=node('span',shortName(s.name),'sc-label');label.append(node('small',s.spoolman?'Spoolman #'+s.spoolman.id+' · '+t(rowFor(id)?.matches?'same':'difference'):t('local')));b.append(dot,label);$('source-list').append(b);}
  if(!visible.length)$('source-list').append(node('p',t('empty'),'sc-empty'));
  const s=inventory?.spools[selected],r=rowFor(selected);
  $('tracker-name').textContent=s?shortName(s.name):'—';$('canonical-name').textContent=r?shortName(r.canonical_name):'—';
  message(!s?t('choose'):!r?t('localHelp'):!r.available?t('unavailable'):r.matches?t('matched'):t('only'));controls();
 }
 async function load(){const [d,c]=await Promise.all([fetch('/api/data').then(r=>{if(!r.ok)throw Error(t('error'));return r.json();}),request('compare')]);inventory=d;comparison=c;render();}
 async function open(){if(!dialog.open)dialog.showModal();loading=true;controls();message(t('loading'));try{await load();$('search').focus();}catch(e){comparison=null;message(e.message,true);}finally{loading=false;controls();}}
 window.openSpoolmanComparison=open;
 $('close').onclick=()=>dialog.close();
 $('settings').onclick=()=>{dialog.close();document.getElementById('nav-settings').click();document.getElementById('spoolman-panel').scrollIntoView({block:'start'});};
 $('search').oninput=()=>{if(!busy)render();};
 dialog.querySelectorAll('[data-sc-filter]').forEach(b=>b.onclick=()=>{if(busy)return;filter=b.dataset.scFilter;dialog.querySelectorAll('[data-sc-filter]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));render();});
 $('refresh').onclick=async()=>{if(busy||loading)return;busy=true;controls();try{await request('refresh-labels',{});await load();}catch(e){comparison=null;message(e.message,true);}finally{busy=false;controls();}};
 $('sync').onclick=async()=>{const r=rowFor(selected);if(busy||loading||!r?.available||r.matches)return;busy=true;controls();try{await request('sync-label',{id:r.id,revision:r.revision});await load();await loadData();message(t('success'));}catch(e){try{await load();}catch(_){comparison=null;}message(e.message,true);}finally{busy=false;controls();}};
 for(const anchor of ['t-spools-hdr','sm-selection-title']){const e=document.getElementById(anchor);if(e){const b=node('button',t('open'),'sc-open');b.type='button';b.onclick=open;e.insertAdjacentElement('afterend',b);new MutationObserver(()=>b.textContent=t('open')).observe(e,{childList:true});}}
 setInterval(()=>{if(dialog.open&&!busy&&!loading&&comparison?.fresh&&Date.now()/1000-comparison.checked_at>60){comparison.fresh=false;comparison.rows.forEach(r=>r.available=false);render();}},1000);
 if(location.hash==='#spoolman-compare')open();
})();
</script>
'''


def install(html):
    return html.replace('</body>', PANEL + SCRIPT + '</body>')
