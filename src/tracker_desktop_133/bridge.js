// Complete 1.3.3 presentation, with explicit 2.0 routes. No legacy write handler.
const DESKTOP_TOKEN=__TOKEN__,DESKTOP_VERSION=__VERSION__;
let desktopRevision='';
let desktopLatestData=null,desktopFormData=null;
let desktopSpoolmanData=null,desktopSpoolmanFormRevision='';
function displayGrams(value){return Number(value).toLocaleString(typeof currentLang==='undefined'?'ru':currentLang,{maximumFractionDigits:1})}
(()=>{
 const original=window.fetch.bind(window);
 window.fetch=async(resource,options={})=>{
  if(typeof resource!=='string'||!resource.startsWith('/api/'))return original(resource,options);
  const options2={...options,headers:{...(options.headers||{}),'X-Tracker-Token':DESKTOP_TOKEN}};
  if(resource.startsWith('/api/core/'))return original(resource.replace('/api/core/','/api/'),options2);
  let pendingKey=null;
  if(!resource.startsWith('/api/history_')){
   if(options2.body&&['/api/spools/add','/api/spools/update','/api/spools/color','/api/spools/delete','/api/spools/calibration','/api/spools/archive','/api/slots','/api/spoolman/attach','/api/spoolman/detach'].includes(resource)){
    const body=JSON.parse(options2.body);
    pendingKey='tracker20-inventory:'+resource+':'+JSON.stringify(body);
    let pending=JSON.parse(sessionStorage.getItem(pendingKey)||'null');
    if(!pending){
     if(!desktopFormData)throw Error('Reload the inventory before changing it.');
     const remote=resource.startsWith('/api/spoolman/');
     const revision=remote?desktopSpoolmanData?.inventory_revision:desktopFormData.inventory_revision;
     const catalogRevision=desktopSpoolmanData?.catalog_revision;
     if(window.desktopConfirmInventory&&!await window.desktopConfirmInventory(resource,body))return new Response('{}',{status:200});
     pending={...body,_inventory_revision:revision,_request_id:crypto.randomUUID(),_confirmed:true};
     if(resource==='/api/spoolman/attach')pending.catalog_revision=catalogRevision;
     sessionStorage.setItem(pendingKey,JSON.stringify(pending));
    }
    options2.body=JSON.stringify(pending);
   }
   if(resource==='/api/guard/decision'&&options2.body){const body=JSON.parse(options2.body);options2.body=JSON.stringify({...body,printer_id:desktopFormData.selected_printer,expected_revision:desktopLatestData.last_guard.revision,confirmed:true})}
   if(options2.body){const body=JSON.parse(options2.body);body._settings_revision=resource==='/api/spoolman/configure'?desktopSpoolmanFormRevision:resource==='/api/select_printer'?desktopFormData?.settings_revision:desktopRevision;options2.body=JSON.stringify(body)}
   resource=resource.replace('/api/','/api/desktop/');
  }
  const response=await original(resource,options2);
  // Retain the same intent after a lost response; never fabricate a new retry ID.
  if(pendingKey&&response.status<500)sessionStorage.removeItem(pendingKey);
  if(resource==='/api/desktop/data'&&response.ok){desktopLatestData=await response.clone().json();desktopRevision=desktopLatestData.settings_revision}
  if(resource==='/api/desktop/spoolman/status'&&response.ok)desktopSpoolmanData=await response.clone().json();
  return response;
 };
})();
async function desktopCore(action,body){const response=await fetch('/api/core/'+action,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw Error(data.error||String(response.status));return data}
function desktopText(ru,en,de=en,uk=en,es=en){return ({ru,en,de,uk,es})[currentLang]||en}
