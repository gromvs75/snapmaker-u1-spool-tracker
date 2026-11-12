"""Task-focused spool inventory layout using the existing forms and API."""
STYLE = '''<style>
#view-spools [data-inventory-pane][hidden]{display:none!important}
.inventory-tabs{display:flex;gap:8px;border-bottom:1px solid var(--border);padding-bottom:14px;margin-bottom:20px;flex-wrap:wrap}
.inventory-tabs button{background:transparent;color:var(--muted)}.inventory-tabs button[aria-pressed=true]{background:#203451;color:#bed9ff}
#inventory-toolbar{display:flex;align-items:center;gap:16px;margin:16px 0;flex-wrap:wrap}#inventory-search{flex:1;min-width:180px;margin:0}#inventory-toolbar .sc-open{margin:0!important}
#inventory-count{font-size:12px;color:var(--muted);margin:12px 0 0}#inventory-empty{color:var(--muted);padding:20px}
#view-spools .spool-inventory thead{display:table-header-group}#view-spools .table-scroll{max-height:480px;overflow:auto}#view-spools .spool-inventory thead th{position:sticky;top:0;background:var(--card);z-index:1}
#view-spools .spool-inventory td{vertical-align:middle;padding:12px}.inventory-name{display:flex;align-items:center;gap:12px;min-width:0}.inventory-name .sm-art{width:40px;height:40px;flex:none}.inventory-name strong{overflow-wrap:anywhere}.inventory-name small{display:block;color:var(--muted);font-size:11px;font-weight:400;margin-top:4px}
#view-spools .spool-inventory .color-picker{margin-left:52px;font-size:12px}#view-spools .spool-inventory input{width:110px!important}.inventory-external{font-size:12px;color:var(--muted)}
#view-spools [data-inventory-pane=add] .card,#view-spools [data-inventory-pane=parameters] .card{max-width:800px}
#view-spools [data-inventory-pane=add] #add-spool-form{display:grid;grid-template-columns:minmax(0,1fr) 140px;gap:14px}#view-spools #new-name{grid-column:1/-1}#view-spools #new-mat,#view-spools #new-weight{max-width:none!important;width:100%;box-sizing:border-box}#view-spools #t-add-btn{grid-column:1/-1;justify-self:start}
#view-spools .inventory-add>summary,#view-spools .calibration-details>summary{list-style:none;pointer-events:none;font-weight:650;margin-bottom:18px}#view-spools .inventory-add>summary::-webkit-details-marker,#view-spools .calibration-details>summary::-webkit-details-marker{display:none}
#view-spools #slots-container{grid-template-columns:1fr 1fr;gap:22px}#inventory-save-status{color:#a6dca0;font-size:13px}
@media(max-width:650px){.inventory-tabs{gap:4px}.inventory-tabs button{font-size:12px;padding:10px}#view-spools #slots-container{grid-template-columns:1fr}#view-spools .spool-inventory{min-width:580px}}
</style>'''
SCRIPT = r'''<script>
(()=>{
 const $=id=>document.getElementById(id),root=$('view-spools');
 const make=(tag,cls)=>{const e=document.createElement(tag);if(cls)e.className=cls;return e;};
 const nav=make('nav','inventory-tabs');nav.setAttribute('aria-label','Spool tasks');root.prepend(nav);
 const panes={},anchors={library:'t-spools-hdr',slots:'t-slots-hdr',add:'t-add-hdr',parameters:'cal-title'};
 for(const [key,id] of Object.entries(anchors)){const pane=make('div');pane.dataset.inventoryPane=key;const card=$(id).closest('.card');root.append(pane);pane.append(card);panes[key]=pane;const b=make('button');b.type='button';b.dataset.inventoryTab=key;b.onclick=()=>show(key);nav.append(b);}
 const toolbar=make('div');toolbar.id='inventory-toolbar';const search=make('input');search.id='inventory-search';search.type='search';search.setAttribute('aria-controls','spools-table');toolbar.append(search);const compare=panes.library.querySelector('.sc-open');if(compare)toolbar.append(compare);$('t-spools-hdr').after(toolbar);
 const count=make('p');count.id='inventory-count';count.setAttribute('role','status');const empty=make('p');empty.id='inventory-empty';panes.library.querySelector('.table-scroll').after(empty,count);
 const status=make('p');status.id='inventory-save-status';status.setAttribute('role','status');root.append(status);
 window.inventorySaved=()=>{status.textContent=currentLang==='ru'?'Изменения сохранены.':'Changes saved.';};
 function show(key){for(const [k,p] of Object.entries(panes))p.hidden=k!==key;nav.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.inventoryTab===key)));status.textContent='';}
 function text(){const ru=currentLang==='ru';const labels=ru?['Библиотека','Головки T0–T3','Добавить катушку','Параметры']:['Library','Toolheads T0–T3','Add spool','Parameters'];nav.querySelectorAll('button').forEach((b,i)=>b.textContent=labels[i]);search.placeholder=ru?'Найти по названию или материалу':'Search name or material';search.setAttribute('aria-label',search.placeholder);empty.textContent=ru?'Катушки не найдены. Измените запрос или добавьте новую катушку.':'No spools found. Change your search or add a spool.';filter();}
 function filter(){const words=search.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);let visible=0;const rows=[...$('spools-table').children];for(const r of rows){const match=words.every(w=>(r.dataset.search||r.textContent).toLocaleLowerCase().includes(w));r.hidden=!match;if(match)visible++;}count.textContent=(currentLang==='ru'?'Показано: ':'Showing: ')+visible+' / '+rows.length;empty.hidden=visible>0;}
 search.oninput=filter;new MutationObserver(filter).observe($('spools-table'),{childList:true});new MutationObserver(text).observe($('nav-spools'),{childList:true});
 for(const d of root.querySelectorAll('.inventory-add,.calibration-details'))d.open=true;
 text();show('library');
})();
</script>'''
def install(html):
    return html.replace('</body>', STYLE+SCRIPT+'</body>')
