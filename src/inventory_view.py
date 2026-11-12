"""Task-focused spool inventory layout using the existing forms and API."""
STYLE = '''<style>
#view-spools [data-inventory-pane][hidden]{display:none!important}
#view-spools:not([hidden]){display:grid;grid-template-columns:175px minmax(0,1fr);gap:24px;align-items:start}.inventory-body{min-width:0}.inventory-tabs{display:grid;gap:8px;border-right:1px solid var(--border);padding-right:16px;position:sticky;top:16px}.inventory-tabs button{text-align:left;width:100%}
.inventory-tabs button{background:transparent;color:var(--muted)}.inventory-tabs button[aria-pressed=true]{background:#203451;color:#bed9ff}
#inventory-toolbar{display:flex;align-items:center;gap:16px;margin:16px 0;flex-wrap:wrap}#inventory-search{flex:1;min-width:180px;margin:0}#inventory-toolbar .sc-open{margin:0!important}
#inventory-count{font-size:12px;color:var(--muted);margin:12px 0 0}#inventory-empty{color:var(--muted);padding:20px}
#view-spools .spool-inventory thead{display:table-header-group}#view-spools .table-scroll{max-height:480px;overflow:auto}#view-spools .spool-inventory thead th{position:sticky;top:0;background:var(--card);z-index:1}
#view-spools .spool-inventory td{vertical-align:middle;padding:12px}.inventory-name{display:flex;align-items:center;gap:12px;min-width:0}.inventory-name .sm-art{width:40px;height:40px;flex:none}.inventory-name strong{overflow-wrap:anywhere}.inventory-name small{display:block;color:var(--muted);font-size:11px;font-weight:400;margin-top:4px}
#view-spools .spool-inventory .color-picker{margin-left:52px;font-size:12px}#view-spools .spool-inventory input{width:110px!important}.inventory-external{font-size:12px;color:var(--muted)}
.inventory-dialog{width:min(720px,calc(100vw - 40px));max-height:85vh;overflow:auto;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:16px;padding:22px}.inventory-dialog::backdrop{background:#0009}.inventory-dialog .card{border:0;padding:0;margin:0}.inventory-dialog .dialog-close{float:right;background:#253147;margin-bottom:16px}.inventory-dialog form{clear:both}.inventory-dialog #new-color-grid{margin:14px 0}.inventory-dialog #new-name{width:100%}.inventory-dialog #new-mat,.inventory-dialog #new-weight{max-width:none!important;width:100%}.inventory-dialog #add-spool-form{display:grid;grid-template-columns:1fr 130px;gap:14px}.inventory-dialog #new-name{grid-column:1/-1}.inventory-dialog #t-add-btn{margin-top:18px}.inventory-dialog summary{list-style:none}.inventory-dialog #cal-form{display:grid;gap:14px}.inventory-dialog #cal-form input,.inventory-dialog #cal-form select{width:100%}.inventory-dialog #cal-form .form-inline{display:flex;gap:12px}.inventory-param-button{display:block;margin:6px 0;background:#253147;font-size:12px}.inventory-dialog #create-head-row{margin:18px 0}.inventory-dialog #create-head{margin-top:8px;width:100%}
#view-spools [data-inventory-pane=add] #add-spool-form{display:grid;grid-template-columns:minmax(0,1fr) 140px;gap:14px}#view-spools #new-name{grid-column:1/-1}#view-spools #new-mat,#view-spools #new-weight{max-width:none!important;width:100%;box-sizing:border-box}#view-spools #t-add-btn{grid-column:1/-1;justify-self:start}
#view-spools .inventory-add>summary,#view-spools .calibration-details>summary{list-style:none;pointer-events:none;font-weight:650;margin-bottom:18px}#view-spools .inventory-add>summary::-webkit-details-marker,#view-spools .calibration-details>summary::-webkit-details-marker{display:none}
#view-spools #slots-container{grid-template-columns:1fr 1fr;gap:22px}#inventory-save-status{color:#a6dca0;font-size:13px}
@media(max-width:740px){#view-spools:not([hidden]){grid-template-columns:1fr}.inventory-tabs{display:flex;border-right:0;border-bottom:1px solid var(--border);position:static;padding:0 0 12px}.inventory-tabs button{width:auto}.inventory-tabs{gap:4px}.inventory-tabs button{font-size:12px;padding:10px}#view-spools #slots-container{grid-template-columns:1fr}#view-spools .spool-inventory{min-width:580px}}
</style>'''
SCRIPT = r'''<script>
(()=>{
 const $=id=>document.getElementById(id),root=$('view-spools');
 const make=(tag,cls)=>{const e=document.createElement(tag);if(cls)e.className=cls;return e;};
 const nav=make('nav','inventory-tabs');nav.setAttribute('aria-label','Spool tasks');const body=make('div','inventory-body');root.prepend(nav,body);
 const panes={},anchors={library:'t-spools-hdr',slots:'t-slots-hdr',add:'t-add-hdr',parameters:'cal-title'};
 for(const [key,id] of Object.entries(anchors)){const pane=make('div');pane.dataset.inventoryPane=key;const card=$(id).closest('.card');body.append(pane);pane.append(card);panes[key]=pane;if(['library','slots'].includes(key)){const b=make('button');b.type='button';b.dataset.inventoryTab=key;b.onclick=()=>show(key);nav.append(b);}}
 const toolbar=make('div');toolbar.id='inventory-toolbar';const search=make('input');search.id='inventory-search';search.type='search';search.setAttribute('aria-controls','spools-table');toolbar.append(search);const compare=panes.library.querySelector('.sc-open');if(compare)toolbar.append(compare);$('t-spools-hdr').after(toolbar);
 const count=make('p');count.id='inventory-count';count.setAttribute('role','status');const empty=make('p');empty.id='inventory-empty';panes.library.querySelector('.table-scroll').after(empty,count);

 const addDialog=make('dialog','inventory-dialog'),paramDialog=make('dialog','inventory-dialog');addDialog.id='inventory-add-dialog';paramDialog.id='inventory-param-dialog';
 document.body.append(addDialog,paramDialog);addDialog.append(panes.add);paramDialog.append(panes.parameters);panes.add.hidden=false;panes.parameters.hidden=false;
 const closeButtons=[];for(const dialog of [addDialog,paramDialog]){const b=make('button','dialog-close');b.type='button';b.onclick=()=>dialog.close();dialog.prepend(b);closeButtons.push(b);}
 const create=make('button');create.type='button';create.id='inventory-create';toolbar.append(create);
 const createAssign=make('button');createAssign.type='button';createAssign.id='inventory-create-assign';$('t-slots-hdr').after(createAssign);
 const headRow=make('label');headRow.id='create-head-row';const headLabel=make('span');const head=make('select');head.id='create-head';head.setAttribute('form','add-spool-form');for(let i=0;i<4;i++){const o=make('option');o.value=String(i+1);o.textContent='T'+i;head.append(o);}headRow.append(headLabel,head);$('new-color-picker').after(headRow);
 const addButton=$('t-add-btn');addButton.setAttribute('form','add-spool-form');headRow.after(addButton);
 let assigning=false,expectedSlots={},opening=false;
 async function openAdd(assign){if(opening)return;opening=true;try{const d=await api('/api/data');expectedSlots={...d.slots};assigning=assign;headRow.hidden=!assign;head.value='1';text();addDialog.showModal();$('new-name').focus();}finally{opening=false;}}
 create.onclick=()=>act(()=>openAdd(false));createAssign.onclick=()=>act(()=>openAdd(true));
 window.inventoryCreateOptions=async()=>{if(!assigning)return {};const slot=head.value;if(expectedSlots[slot]&&!confirm((currentLang==='ru'?'Заменить текущую катушку на ':'Replace current spool on ')+'T'+(Number(slot)-1)+'?'))return null;return {assign_slot:slot,expected_slot:expectedSlots[slot]};};
 window.inventoryCreated=()=>{addDialog.close();show(assigning?'slots':'library');window.inventorySaved();};
 window.inventoryParameters=id=>{$('cal-spool').value=id;$('cal-spool').onchange?.();paramDialog.showModal();$('cal-mode').focus();};
 window.inventoryParametersSaved=()=>{paramDialog.close();window.inventorySaved();};
 const status=make('p');status.id='inventory-save-status';status.setAttribute('role','status');body.append(status);
 window.inventorySaved=()=>{status.textContent=currentLang==='ru'?'Изменения сохранены.':'Changes saved.';};
 function show(key){for(const k of ['library','slots'])panes[k].hidden=k!==key;nav.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.inventoryTab===key)));status.textContent='';}
 function text(){const ru=currentLang==='ru';const labels=ru?['Библиотека','Головки T0–T3']:['Library','Toolheads T0–T3'];nav.querySelectorAll('button').forEach((b,i)=>b.textContent=labels[i]);create.textContent=ru?'Добавить катушку':'Add spool';createAssign.textContent=ru?'Добавить и назначить':'Add and assign';addButton.textContent=assigning?createAssign.textContent:create.textContent;headLabel.textContent=ru?'Назначить на головку':'Assign to toolhead';closeButtons.forEach(b=>b.textContent=ru?'Закрыть':'Close');search.placeholder=ru?'Найти по названию или материалу':'Search name or material';search.setAttribute('aria-label',search.placeholder);empty.textContent=ru?'Катушки не найдены. Измените запрос или добавьте новую катушку.':'No spools found. Change your search or add a spool.';filter();}
 function filter(){const words=search.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);let visible=0;const rows=[...$('spools-table').children];for(const r of rows){const match=words.every(w=>(r.dataset.search||r.textContent).toLocaleLowerCase().includes(w));r.hidden=!match;if(match)visible++;}count.textContent=(currentLang==='ru'?'Показано: ':'Showing: ')+visible+' / '+rows.length;empty.hidden=visible>0;}
 search.oninput=filter;new MutationObserver(filter).observe($('spools-table'),{childList:true});new MutationObserver(text).observe($('nav-spools'),{childList:true});
 for(const d of document.querySelectorAll('.inventory-add,.calibration-details'))d.open=true;
 text();show('library');
})();
</script>'''
def install(html):
    return html.replace('</body>', STYLE+SCRIPT+'</body>')
