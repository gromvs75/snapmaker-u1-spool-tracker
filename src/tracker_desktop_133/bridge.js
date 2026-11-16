// Complete 1.3.3 presentation, with explicit 2.0 routes. No legacy write handler.
const DESKTOP_TOKEN=__TOKEN__,DESKTOP_VERSION=__VERSION__;
let desktopRevision='';
function displayGrams(value){return Number(value).toLocaleString(typeof currentLang==='undefined'?'ru':currentLang,{maximumFractionDigits:1})}
(()=>{
 const original=window.fetch.bind(window);
 window.fetch=async(resource,options={})=>{
  if(typeof resource!=='string'||!resource.startsWith('/api/'))return original(resource,options);
  const options2={...options,headers:{...(options.headers||{}),'X-Tracker-Token':DESKTOP_TOKEN}};
  if(!resource.startsWith('/api/history_')){
   if(options2.body){const body=JSON.parse(options2.body);body._settings_revision=desktopRevision;options2.body=JSON.stringify(body)}
   resource=resource.replace('/api/','/api/desktop/');
  }
  const response=await original(resource,options2);
  if(resource==='/api/desktop/data'&&response.ok)desktopRevision=(await response.clone().json()).settings_revision;
  return response;
 };
})();
