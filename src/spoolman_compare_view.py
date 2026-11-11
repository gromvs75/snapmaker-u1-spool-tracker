"""Report variant: light comparison workspace with a fixed right-hand editor."""
PANEL = r'''
<style>
#sc-dialog {--sc-orange:#ff6500;--sc-ink:#45494d;--sc-muted:#8b9094;--sc-line:#e9e9e9;box-sizing:border-box;position:fixed;inset:0;width:100vw;height:100dvh;max-width:none;max-height:none;margin:0;padding:0;border:0;background:#fff;color:var(--sc-ink);font:14px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
#sc-dialog::backdrop{background:#fff}#sc-dialog *{box-sizing:border-box}#sc-dialog [hidden]{display:none!important}
#sc-dialog button,#sc-dialog input{font:inherit}#sc-dialog button{cursor:pointer;box-shadow:none;transition:background .12s}#sc-dialog button:focus-visible{outline:3px solid #ff9c59;outline-offset:3px}#sc-dialog button:disabled{cursor:default;opacity:.55}
#sc-dialog h2,#sc-dialog h3,#sc-dialog p{margin:0}#sc-dialog h2{font-size:16px;font-weight:650;color:#666b6e;text-transform:none;letter-spacing:0;border:0;padding:0}#sc-dialog h3{font-size:14px;font-weight:600}
.sc-workspace{display:grid;grid-template-columns:calc(7.5vw - 10px) minmax(0,1fr) 33.25vw;gap:10px;min-height:100%;padding:21px 13px 16px 0}
.sc-rail{display:flex;align-items:center;flex-direction:column;border-right:1px solid #efefef;padding-top:26px;gap:14px}
#sc-dialog .sc-logo{display:grid;place-items:center;width:41px;height:41px;border-radius:50%;background:#e9e9e9;color:#74797d;font-weight:700;margin-bottom:20px}
#sc-dialog .sc-nav{background:transparent;border:0;border-radius:7px;padding:7px 3px;min-height:26px;width:70px;text-align:center;font-size:11px;color:#7a7f83;display:flex;gap:5px;align-items:center;justify-content:center}
#sc-dialog .sc-nav:hover{background:#f3f3f3}.sc-nav svg{width:15px;height:15px;flex:none;stroke:currentColor;fill:none;stroke-width:1.6}.sc-nav[aria-current]{color:#ff6500!important;background:#fff2e8!important}
#sc-dialog .sc-help{margin-top:auto;width:41px;height:41px;border:0;background:#eee;color:#888;border-radius:6px}
.sc-main{display:grid;grid-template-rows:214px 301px minmax(461px,1fr);gap:14px;padding:7px 0 1px;min-width:0}
.sc-card{border:1px solid #eaeaea;border-radius:10px;background:#f8f8f8;overflow:hidden}
.sc-slots-card{padding:42px 17px 20px 31px}.sc-slot-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:19px;margin-top:16px}
#sc-dialog .sc-slot{display:flex;flex-direction:column;align-items:flex-start;min-width:0;height:114px;padding:10px;border:1px solid #d9d9d9;border-radius:7px;background:#fff;color:#62676a;text-align:left}
.sc-slot strong{font-size:13px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;max-width:100%}.sc-slot small{color:#92979a;margin-top:6px}.sc-slot-foot{margin-top:auto;display:flex;align-items:center;gap:8px;font-size:12px;color:#858a8e}
.sc-dot{display:inline-block;width:21px;height:21px;border-radius:50%;background:#d1d3d3;border:1px solid #0000000c;flex:none}
.sc-inventory{padding:19px 16px}.sc-inventory h2{margin:0 18px 16px!important}.sc-inventory-table{background:#fff;border-radius:7px;padding:0 42px 0 21px;max-height:232px;overflow:auto}
.sc-inventory-row{display:grid;grid-template-columns:minmax(0,2.54fr) 1.06fr 2.01fr 100px;gap:16px;min-height:55px;align-items:center;border-bottom:1px solid #eee}.sc-inventory-row:last-child{border:0}.sc-inventory-name{display:flex;gap:13px;align-items:center;min-width:0}.sc-ellipsis{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#sc-dialog .sc-small{border:0;border-radius:5px;background:#ededed;color:#757a7e;padding:6px 9px;min-height:28px;font-size:12px;text-align:center}#sc-dialog .sc-small:hover{background:#e3e3e3}
.sc-catalog{margin-top:1px;padding:26px 15px 15px;display:flex;flex-direction:column}.sc-tabs{display:flex;gap:22px;padding:0 18px;margin-bottom:17px}#sc-dialog .sc-tab{border:0;min-height:0;padding:4px 0;background:none;color:#9a9ea0;font-size:13px}#sc-dialog .sc-tab[aria-pressed=true]{color:#555b60;font-weight:650}
.sc-source-grid{display:grid;grid-template-columns:44.5% minmax(0,1fr);gap:4px;flex:1;min-height:0}.sc-source-list,.sc-source-detail{background:#fff;border:1px solid #efefef;border-radius:7px;padding:16px 19px;min-width:0}.sc-source-list h3{color:#999;margin-bottom:17px!important}
#sc-dialog .sc-source-item{display:flex;align-items:center;gap:14px;width:100%;min-height:55px;padding:8px 0;border:0;border-top:1px solid #f0f0f0;border-radius:0;background:none;color:#858a8e;text-align:left;font-size:13px}.sc-source-item .sc-count{margin-left:auto;font-size:11px;color:#a2a5a7;white-space:nowrap}.sc-source-item .sc-dot{width:19px;height:19px}#sc-dialog .sc-source-item:hover{background:#fafafa}
.sc-source-detail{display:flex;flex-direction:column}#sc-title:focus{outline:none}.sc-detail-header{display:flex;gap:21px;align-items:center;border-bottom:1px solid #ddd;padding-bottom:19px;margin-bottom:16px}.sc-detail-tile{width:54px;height:54px;background:#ededed;border-radius:6px;display:grid;place-items:center;flex:none;font-size:16px;color:#aaa}.sc-detail-header strong{display:block;font-size:14px}.sc-detail-header small{display:block;color:#999;margin-top:5px}.sc-detail-row{display:flex;gap:10px;justify-content:space-between;color:#8f9497;margin:10px 0;font-size:13px}.sc-detail-row span:last-child{color:#666;max-width:65%;text-align:right;overflow-wrap:anywhere}
#sc-dialog .sc-detail-action{margin-top:auto;min-height:59px;background:#eee;border:0;width:100%;border-radius:6px;color:#777}
.sc-editor{border:1.5px solid var(--sc-orange);border-left-width:13px;border-radius:13px 13px 0 0;background:#fff;padding:39px 26px 24px;min-width:0}
#sc-dialog .sc-editor h2{font-size:17px;margin-bottom:38px;color:#686d70}.sc-compare{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:47px;padding:0 7px}.sc-column{min-width:0}.sc-column:first-child{border-right:1px solid #c9cbcc;padding-right:31px;margin-right:-16px}.sc-column h3{color:#777;font-size:15px!important;margin-bottom:19px!important}.sc-field{height:46px;min-width:0}.sc-field small{display:block;font-size:10px;color:#a1a5a7;line-height:14px}.sc-field span{display:block;font-size:12px;line-height:17px;color:#686d70;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sc-field:last-child{height:28px}.sc-field:first-child span{white-space:normal;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}.sc-field .sc-different{color:#de650e;font-weight:600}
.sc-sync-wrap{border-top:1px solid #bdbfc0;margin-top:29px;padding-top:25px}#sc-sync{width:100%;height:46px;border:0;border-radius:7px;background:var(--sc-orange);color:white;font-weight:650;font-size:13px}#sc-sync:hover:not(:disabled){background:#ed5e00}#sc-sync:disabled{opacity:1;background:#f2f2f2;color:#92979a}
#sc-message{min-height:43px;font-size:11px;line-height:15px;color:#8e9396;padding:10px 0 5px}#sc-message[data-error=true]{color:#b9431b}.sc-queue{display:flex;flex-direction:column;gap:12px}
#sc-dialog .sc-queue-item{height:55px;flex:none;display:flex;gap:17px;align-items:center;background:white;border:0;border-bottom:1px solid #eee;border-radius:0;padding:10px 7px;color:#7b8084;text-align:left;width:100%;font-size:12px}.sc-queue-item .sc-label{flex:1;min-width:0}.sc-badge{font-size:10px;color:#aaa;border-radius:8px;background:#f2f2f2;padding:2px 7px;white-space:nowrap}#sc-dialog .sc-queue-item[aria-pressed=true]{border:1.5px solid var(--sc-orange);border-radius:10px}.sc-queue-item[aria-pressed=true] .sc-dot{background:var(--sc-orange)!important}.sc-queue-item[aria-pressed=true] .sc-badge{background:#ffe1cc;color:#df7835}
.sc-empty{color:#999;font-size:13px;padding:20px 0}.sc-open{margin-left:15px!important;font-size:13px!important}
@media(min-width:1600px){.sc-workspace{max-width:1800px;margin:auto}}
@media(max-width:1000px){.sc-workspace{grid-template-columns:65px minmax(0,1fr) 35%;gap:10px}.sc-slots-card{padding:30px 15px}.sc-slot-grid{gap:8px}.sc-editor{padding:30px 16px}.sc-compare{gap:20px;padding:0}.sc-column:first-child{padding-right:15px;margin-right:-10px}.sc-inventory-row{grid-template-columns:minmax(0,1fr) 48px 70px;gap:8px}.sc-inventory-row .sc-inventory-material{display:none}.sc-source-grid{grid-template-columns:1fr}.sc-source-detail{display:none}.sc-tabs{gap:15px}.sc-nav{width:58px!important}.sc-nav span{display:none}.sc-nav svg{width:20px;height:20px}}
@media(max-width:720px){.sc-workspace{grid-template-columns:48px minmax(0,1fr);padding:12px 10px 12px 0}.sc-main{grid-column:2;grid-row:2;grid-template-rows:auto auto auto;padding:0}.sc-editor{grid-column:2;grid-row:1;border-left-width:7px;border-radius:10px;padding:24px 18px}.sc-rail{grid-row:1/3;padding-top:8px}.sc-nav{width:39px!important}.sc-editor h2{margin-bottom:24px!important}.sc-queue{max-height:205px;overflow:auto}.sc-slot-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.sc-slots-card{padding:20px 12px}.sc-inventory{padding:16px 8px}.sc-inventory-table{padding:0 8px}.sc-inventory-row{grid-template-columns:minmax(0,1fr) 64px}.sc-inventory-row .sc-small{display:none}.sc-tabs{gap:15px;padding:0;flex-wrap:wrap;margin-bottom:16px}.sc-catalog{padding:15px}.sc-source-list{padding:14px}.sc-help{display:none}}
</style>
<dialog id="sc-dialog" aria-labelledby="sc-title">
 <div class="sc-workspace">
  <nav class="sc-rail" aria-label="Tracker">
   <div class="sc-logo">U1</div>
   <button class="sc-nav" data-sc-nav="overview" title="Обзор"><svg viewBox="0 0 24 24"><path d="M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z"/></svg><span data-sc-text="overview"></span></button>
   <button class="sc-nav" data-sc-nav="spools" title="Катушки"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/></svg><span data-sc-text="spools"></span></button>
   <button class="sc-nav" data-sc-nav="history" title="История"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 3"/></svg><span data-sc-text="history"></span></button>
   <button class="sc-nav" data-sc-nav="settings" title="Настройки"><svg viewBox="0 0 24 24"><path d="M4 7h16M4 17h16"/><circle cx="8" cy="7" r="3"/><circle cx="16" cy="17" r="3"/></svg><span data-sc-text="settings"></span></button>
   <button class="sc-nav" id="sc-current" aria-current="page" title="Сравнение"><svg viewBox="0 0 24 24"><path d="M12 3v18M3 6h6M15 6h6M3 12h6M15 12h6M3 18h6M15 18h6"/></svg><span data-sc-text="compare"></span></button>
   <button class="sc-nav" id="sc-refresh" title="Обновить каталог"><svg viewBox="0 0 24 24"><path d="M20 9a8 8 0 1 0 0 6M20 3v6h-6"/></svg><span data-sc-text="refresh"></span></button>
   <button class="sc-nav" id="sc-close" title="Закрыть сравнение"><svg viewBox="0 0 24 24"><path d="m14 5-7 7 7 7M7 12h14"/></svg><span data-sc-text="back"></span></button>
   <button class="sc-help" id="sc-help" aria-label="О сравнении">?</button>
  </nav>
  <main class="sc-main">
   <section class="sc-card sc-slots-card"><h2 data-sc-text="slots"></h2><div class="sc-slot-grid" id="sc-slots"></div></section>
   <section class="sc-card sc-inventory"><h2 data-sc-text="inventory"></h2><div class="sc-inventory-table" id="sc-inventory" role="list"></div></section>
   <section class="sc-card sc-catalog">
    <div class="sc-tabs" role="group" aria-label="Фильтр катушек">
     <button class="sc-tab" data-sc-filter="all" aria-pressed="true" data-sc-text="catalog"></button>
     <button class="sc-tab" data-sc-filter="different" aria-pressed="false" data-sc-text="different"></button>
     <button class="sc-tab" data-sc-filter="same" aria-pressed="false" data-sc-text="same"></button>
     <button class="sc-tab" data-sc-filter="local" aria-pressed="false" data-sc-text="local"></button>
    </div>
    <div class="sc-source-grid"><div class="sc-source-list"><h3 data-sc-text="spools"></h3><div id="sc-source-list"></div></div><div class="sc-source-detail" id="sc-source-detail"></div></div>
   </section>
  </main>
  <aside class="sc-editor" aria-labelledby="sc-title">
   <h2 id="sc-title" data-sc-text="title"></h2>
   <div class="sc-compare"><div class="sc-column"><h3>Tracker</h3><div id="sc-tracker-fields"></div></div><div class="sc-column"><h3>Spoolman</h3><div id="sc-canonical-fields"></div></div></div>
   <div class="sc-sync-wrap"><button id="sc-sync" disabled data-sc-text="sync"></button></div>
   <p id="sc-message" role="status" aria-live="polite"></p>
   <div id="sc-queue" class="sc-queue" aria-label="Катушки Spoolman"></div>
  </aside>
 </div>
</dialog>
'''

SCRIPT = r'''
<script>
(() => {
 const $=id=>document.getElementById('sc-'+id), dialog=$('dialog');
 const words={ru:{overview:'Обзор',spools:'Катушки',history:'История',settings:'Настройки',compare:'Сравнение',refresh:'Обновить',back:'Назад',slots:'Активные слоты · T0–T3',inventory:'Библиотека катушек',catalog:'Каталог',different:'Различия',same:'Совпадают',local:'Локальные',title:'Сравнение названий',sync:'Синхронизировать название',synced:'Название совпадает',name:'Название',manufacturer:'Производитель в названии',material:'Материал',color:'Цвет',source:'ID катушки',missing:'Не указан',empty:'Нет катушек',choose:'Выберите катушку Spoolman',only:'Изменяется только название в Tracker.',unavailable:'Обновите каталог: данные недоступны или устарели.',localHelp:'Локальная катушка — нет связи со Spoolman.',success:'Название обновлено в Tracker.',loading:'Загрузка…',syncing:'Синхронизация…',remaining:'Остаток',details:'Открыть настройки Spoolman',matched:'Совпадает',difference:'Различие',open:'Сравнить названия',unknown:'Не задан',error:'Не удалось загрузить сравнение.',close:'Закрыть сравнение'},en:{overview:'Overview',spools:'Spools',history:'History',settings:'Settings',compare:'Compare',refresh:'Refresh',back:'Back',slots:'Active slots · T0–T3',inventory:'Spool inventory',catalog:'Catalog',different:'Differences',same:'Matching',local:'Local',title:'Compare spool names',sync:'Sync name to Tracker',synced:'Name is up to date',name:'Name',manufacturer:'Manufacturer in name',material:'Material',color:'Color',source:'Spool ID',missing:'Missing',empty:'No spools',choose:'Select a Spoolman spool',only:'Only the name in Tracker changes.',unavailable:'Refresh the catalog: data is unavailable or stale.',localHelp:'Local spool — not linked to Spoolman.',success:'Name updated in Tracker.',loading:'Loading…',syncing:'Syncing…',remaining:'Remaining',details:'Open Spoolman settings',matched:'Matches',difference:'Different',open:'Compare names',unknown:'Not set',error:'Could not load comparison.',close:'Close comparison'}};
 const t=key=>(words[inventory?.language||currentLang]||words.en)[key];
 let inventory=null, comparison=null, selected=null, filter='all', busy=false;
 function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
 function dot(color){const e=node('span',undefined,'sc-dot');if(/^#[0-9a-f]{6}$/i.test(color||''))e.style.backgroundColor=color;e.setAttribute('aria-hidden','true');return e;}
 function shortName(name){return (name||'').replace(/^\[Spoolman #\d+\]\s*/,'');}
 function rowFor(id){return comparison?.rows.find(r=>r.id===id);}
 function setMessage(text,error=false){$('message').textContent=text;$('message').dataset.error=String(error);}
 async function request(action,body){const r=await fetch('/api/spoolman/'+action,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error(d.error||t('error'));return d;}
 function btn(text,fn,cls){const b=node('button',text,cls);b.type='button';b.onclick=fn;return b;}
 function select(id){if(busy)return;selected=id;render();}
 function fields(target,values,changed){target.replaceChildren();for(const [key,value] of values){const f=node('div',undefined,'sc-field');f.append(node('small',t(key)));const v=node('span',value||'—',changed&&key==='name'?'sc-different':'');v.title=value||'—';f.append(v);target.append(f);}}
 function render(){
  dialog.querySelectorAll('[data-sc-text]').forEach(e=>e.textContent=t(e.dataset.scText));
  const entries=Object.entries(inventory?.spools||{}), rows=comparison?.rows||[];
  if(!entries.some(([id])=>id===selected))selected=rows[0]?.id||entries[0]?.[0]||null;
  const spool=inventory?.spools[selected], row=rowFor(selected);
  $('slots').replaceChildren();
  for(let i=1;i<=4;i++){const id=inventory?.slots[String(i)],s=inventory?.spools[id];const b=btn('',()=>s&&select(id),'sc-slot');b.disabled=!s;b.append(node('strong',s?shortName(s.name):'—'),node('small','T'+(i-1)+(s?' · '+s.material:'')));const foot=node('div',undefined,'sc-slot-foot');foot.append(dot(s?.color),node('span',s?s.remaining_g+' g':'—'));b.append(foot);$('slots').append(b);}
  $('inventory').replaceChildren();
  for(const [id,s] of entries){const r=node('div',undefined,'sc-inventory-row');r.setAttribute('role','listitem');const name=node('div',undefined,'sc-inventory-name');name.append(dot(s.color));const n=node('span',shortName(s.name),'sc-ellipsis');n.title=s.name;name.append(n);r.append(name,node('span',s.material,'sc-inventory-material'),node('span',s.remaining_g+' g'),btn(t('compare'),()=>select(id),'sc-small'));$('inventory').append(r);}
  if(!entries.length)$('inventory').append(node('p',t('empty'),'sc-empty'));
  $('source-list').replaceChildren();
  const visible=entries.filter(([id,s])=>filter==='all'||(filter==='local'?!s.spoolman:filter==='same'?rowFor(id)?.matches:rowFor(id)&&!rowFor(id).matches));
  for(const [id,s] of visible){const b=btn('',()=>select(id),'sc-source-item');const n=node('span',shortName(s.name),'sc-ellipsis');n.title=s.name;b.append(dot(s.color),n,node('span',s.spoolman?'#'+s.spoolman.id:t('local'),'sc-count'));$('source-list').append(b);}
  if(!visible.length)$('source-list').append(node('p',t('empty'),'sc-empty'));
  const detail=$('source-detail');detail.replaceChildren();
  if(spool){const h=node('div',undefined,'sc-detail-header');h.append(node('div',spool.spoolman?'S':'U1','sc-detail-tile'));const n=node('div');n.append(node('strong',row?.manufacturer||spool.material),node('small',row?.filament_name||shortName(spool.name)));h.append(n);detail.append(h);
   for(const [label,value] of [[t('name'),shortName(spool.name)],[t('material'),spool.material],[t('remaining'),spool.remaining_g+' g'],[t('source'),spool.spoolman?'Spoolman #'+spool.spoolman.id:t('local')]]){const p=node('div',undefined,'sc-detail-row');p.append(node('span',label),node('span',value));detail.append(p);}detail.append(btn(t('details'),()=>navigate('settings'),'sc-detail-action'));}
  fields($('tracker-fields'),[['name',spool?shortName(spool.name):'—'],['manufacturer',row?.manufacturer&&(shortName(spool?.name).toLowerCase()===row.manufacturer.toLowerCase()||shortName(spool?.name).toLowerCase().startsWith(row.manufacturer.toLowerCase()+' '))?row.manufacturer:t('missing')],['material',spool?.material],['color',spool?.color||t('unknown')],['source',spool?.spoolman?'#'+spool.spoolman.id:'—']],row&&!row.matches);
  fields($('canonical-fields'),[['name',row?shortName(row.canonical_name):'—'],['manufacturer',row?.manufacturer||t('missing')],['material',row?.canonical_material],['color',row?.canonical_color||t('unknown')],['source',row?'#'+row.spoolman_id:'—']],false);
  $('sync').disabled=busy||!row||!row.available||row.matches;$('sync').textContent=t(busy?'syncing':row?.matches?'synced':'sync');
  setMessage(!spool?t('choose'):!row?t('localHelp'):!row.available?t('unavailable'):t('only'));
  $('queue').replaceChildren();
  for(const r of rows){const b=btn('',()=>select(r.id),'sc-queue-item');b.setAttribute('aria-pressed',String(r.id===selected));b.append(dot(r.color));const n=node('span',shortName(r.tracker_name),'sc-label sc-ellipsis');n.title=r.tracker_name;b.append(n,node('span',t(r.matches?'matched':'difference'),'sc-badge'));$('queue').append(b);}
  if(!rows.length)$('queue').append(node('p',t('choose'),'sc-empty'));
 }
 async function load(){const [d,c]=await Promise.all([fetch('/api/data').then(r=>{if(!r.ok)throw Error(t('error'));return r.json();}),request('compare')]);inventory=d;comparison=c;render();}
 function navigate(view){dialog.close();document.getElementById('nav-'+view)?.click();}
 async function open(){if(!dialog.open)dialog.showModal();$('sync').disabled=true;setMessage(t('loading'));try{await load();$('title').setAttribute('tabindex','-1');$('title').focus();}catch(e){comparison=null;$('sync').disabled=true;setMessage(e.message,true);}}
 window.openSpoolmanComparison=open;
 dialog.querySelectorAll('[data-sc-nav]').forEach(b=>b.onclick=()=>navigate(b.dataset.scNav));
 dialog.querySelectorAll('[data-sc-filter]').forEach(b=>b.onclick=()=>{filter=b.dataset.scFilter;dialog.querySelectorAll('[data-sc-filter]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));render();});
 $('close').onclick=()=>dialog.close();$('current').onclick=()=>$('title').scrollIntoView({block:'nearest'});
 $('help').onclick=()=>setMessage(t('only')+' '+t('localHelp'));
 $('refresh').onclick=async()=>{if(busy)return;busy=true;$('refresh').disabled=true;$('sync').disabled=true;setMessage(t('loading'));try{await request('refresh-labels',{});await load();}catch(e){setMessage(e.message,true);}finally{busy=false;$('refresh').disabled=false;const r=rowFor(selected);$('sync').disabled=!r?.available||r.matches;$('sync').textContent=t(r?.matches?'synced':'sync');}};
 $('sync').onclick=async()=>{const row=rowFor(selected);if(busy||!row?.available||row.matches)return;busy=true;$('sync').disabled=true;$('sync').textContent=t('syncing');try{await request('sync-label',{id:row.id,revision:row.revision});await load();await loadData();setMessage(t('success'));}catch(e){try{await load();}catch(_){}setMessage(e.message,true);}finally{busy=false;const r=rowFor(selected);$('sync').disabled=!r?.available||r.matches;$('sync').textContent=t(r?.matches?'synced':'sync');}};
 for(const anchor of ['t-spools-hdr','sm-selection-title']){const e=document.getElementById(anchor);if(e){const b=btn(t('open'),open,'sc-open');e.insertAdjacentElement('afterend',b);new MutationObserver(()=>b.textContent=t('open')).observe(e,{childList:true});}}
 setInterval(()=>{if(dialog.open&&!busy&&comparison?.fresh&&Date.now()/1000-comparison.checked_at>60){comparison.fresh=false;comparison.rows.forEach(r=>r.available=false);render();}},1000);
 if(location.hash==='#spoolman-compare')open();
})();
</script>
'''


def install(html):
    return html.replace('</body>', PANEL + SCRIPT + '</body>')
