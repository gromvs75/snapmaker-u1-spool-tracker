"""Sectioned settings layout; existing forms retain their API handlers."""
STYLE = '''<style>
#view-settings[hidden],[data-settings-pane][hidden],[data-sm-pane][hidden]{display:none!important}
#view-settings{display:grid;grid-template-columns:175px minmax(0,1fr);gap:24px;align-items:start}
.settings-nav{display:grid;gap:8px;border-right:1px solid var(--border);padding-right:16px;position:sticky;top:16px}
.settings-nav button{background:transparent;text-align:left;color:var(--muted);width:100%;padding:12px}
.settings-nav button[aria-pressed=true]{background:#1c304d;color:#bad5ff}
.settings-body{min-width:0}.settings-body .card{margin-top:0!important;width:100%;box-sizing:border-box}
#view-settings #printer-status{position:static;max-width:none;display:inline-block;margin-top:16px}
#view-settings .printer-address{grid-template-columns:minmax(0,1fr) 110px;max-width:600px}
#view-settings .printer-actions{display:flex;flex-wrap:wrap;border-top:1px solid var(--border);padding-top:18px;margin-top:20px;gap:10px}
#view-settings .printer-actions button{margin:0}.settings-form-footer{border-top:1px solid var(--border);padding-top:18px;margin-top:20px;display:flex;gap:10px;flex-wrap:wrap}
.settings-tabs{display:flex;gap:18px;border-bottom:1px solid var(--border);margin:16px 0 20px;flex-wrap:wrap}
.settings-tabs button{background:none;color:var(--muted);border-radius:0;padding:10px 0;border-bottom:2px solid transparent}
.settings-tabs button[aria-pressed=true]{color:#bad5ff;border-bottom-color:#5a98f5}
#sm-selection{margin:0;padding:0;border:0}#sm-selection-title{display:none}
#sm-attach{display:grid;grid-template-columns:minmax(0,1fr) 260px;align-items:start;gap:20px}
#sm-spool{display:none}#sm-picker{width:100%}#sm-visual-list{border:1px solid var(--border);border-radius:10px;overflow:auto;max-height:510px}
.sm-spool-row{display:grid;grid-template-columns:44px minmax(0,1fr) auto;align-items:center;gap:12px;width:100%;border:0;border-bottom:1px solid var(--border);background:transparent;color:var(--text);border-radius:0;text-align:left;padding:12px;font-size:13px}
.sm-spool-row[aria-pressed=true]{background:#1c304d;box-shadow:inset 3px 0 #73aaff}.sm-spool-row small{display:block;color:var(--muted);font-weight:400;margin-top:4px}.sm-spool-row strong{overflow-wrap:anywhere}.sm-spool-row .sm-weight{white-space:nowrap;font-size:12px}
.sm-art{width:44px;height:44px;display:block;flex:none}.sm-inspector{padding:18px;border:1px solid var(--border);border-radius:12px;background:#111a28;min-width:0}.sm-inspector h3{margin:0 0 16px}.sm-inspector p{overflow-wrap:anywhere}.sm-inspector label{display:block;font-size:13px;color:var(--muted);margin:14px 0 6px}.sm-inspector button,.sm-inspector select{width:100%;margin:0!important;box-sizing:border-box}.sm-inspector-actions{display:grid;gap:10px;margin-top:16px}.sm-inspector .sm-art{width:64px;height:64px}.sm-inspector button{font-size:13px;padding:12px 8px}.sm-inspector button:not(#sm-assign){background:#253147;color:var(--text)}.sm-inspector button:disabled{opacity:.5;cursor:default}
#sm-linked{display:none}#sm-summary{margin:12px 0}#sm-detach-help{font-size:12px;line-height:1.6}#sm-connect{gap:18px}#sm-history{border:0;margin:0;padding:0}#sm-history summary{display:none}
@media(max-width:1000px){#view-settings{grid-template-columns:145px minmax(0,1fr);gap:16px}#sm-attach{grid-template-columns:minmax(0,1fr) 220px}.sm-spool-row{grid-template-columns:36px minmax(0,1fr)}.sm-weight{grid-column:2}.sm-art{width:36px;height:36px}}
@media(max-width:740px){#view-settings{grid-template-columns:1fr}.settings-nav{display:flex;position:static;border:0;overflow:auto;padding:0}.settings-nav button{white-space:nowrap;width:auto}#sm-attach{grid-template-columns:1fr}.sm-spool-row{grid-template-columns:44px minmax(0,1fr) auto}.sm-weight{grid-column:auto}}
</style>'''
SCRIPT = r'''<script>
(() => {
 const $=id=>document.getElementById(id), root=$('view-settings');
 const node=(tag,cls)=>{const e=document.createElement(tag);if(cls)e.className=cls;return e;};
 const nav=node('nav','settings-nav'),body=node('div','settings-body');nav.setAttribute('aria-label','Settings sections');
 const panes={};for(const key of ['printer','spoolman','accounting','backup']){const p=node('div');p.dataset.settingsPane=key;panes[key]=p;body.append(p);const b=node('button');b.type='button';b.dataset.settingsSection=key;b.onclick=()=>show(key);nav.append(b);}
 root.prepend(nav,body);
 const printer=$('printer-title').closest('.card'),reserve=$('reserve-label').closest('.card'),backup=$('backup-title').closest('.card'),sm=$('spoolman-panel');
 panes.printer.append(printer);panes.spoolman.append(sm);panes.accounting.append(reserve);panes.backup.append(backup);
 const account=node('div','card'),h=node('h2');h.id='settings-account-title';account.append(h);panes.accounting.prepend(account);
 for(const e of [$('printer-enabled').closest('label'),$('guard-mode').closest('.guard-control'),$('guard-mode-help')])account.append(e);
 for(const id of ['printer-enabled','guard-mode'])$(id).setAttribute('form','printer-form');
 const saved=node('p');saved.id='settings-save-result';saved.setAttribute('role','status');saved.className='subtitle';body.append(saved);window.reportSettingsSaved=()=>{saved.textContent=currentLang==='ru'?'Настройки сохранены.':'Settings saved.';};
 const save=node('button');save.type='submit';save.id='accounting-save';save.setAttribute('form','printer-form');const footer=node('div','settings-form-footer');footer.append(save);account.append(footer);
 $('printer-form').querySelector('.printer-actions').append($('heads-read'));
 for(const form of [$('reserve-form'),$('sm-connect')]){const action=form.querySelector('.form-inline');if(action)action.classList.add('settings-form-footer');}
 root.querySelector(':scope > .settings-grid')?.remove();
 const tabs=node('nav','settings-tabs');tabs.setAttribute('aria-label','Spoolman sections');sm.querySelector('h2').after(tabs);
 const smpanes={};for(const key of ['connection','spools','usage']){const p=node('div');p.dataset.smPane=key;smpanes[key]=p;sm.append(p);const b=node('button');b.type='button';b.dataset.smTab=key;b.onclick=()=>showSM(key);tabs.append(b);}
 for(const id of ['sm-help','sm-summary','sm-connect','sm-status'])smpanes.connection.append($(id));
 smpanes.spools.append($('sm-selection'));smpanes.usage.append($('sm-history'));$('sm-history').open=true;
 sm.append($('sm-error'));
 const inspector=node('aside','sm-inspector');inspector.id='sm-inspector';const title=node('h3');title.id='sm-inspector-title';const details=node('div');details.id='sm-selected-details';const label=node('label');label.htmlFor='sm-head';label.id='sm-head-label';const actions=node('div','sm-inspector-actions');actions.id='sm-inspector-actions';
 inspector.append(title,details,label,$('sm-head'),actions);actions.append($('sm-assign'));
 const detach=node('button');detach.id='sm-detach-selected';detach.type='button';actions.append(detach);
 const compare=$('sm-selection').querySelector('.sc-open');if(compare)actions.append(compare);
 const refresh=node('button');refresh.id='sm-refresh-selected';refresh.type='button';refresh.onclick=()=>$('sm-refresh').click();actions.append(refresh);
 $('sm-attach').append(inspector);const list=node('div');list.id='sm-visual-list';$('sm-spool').after(list);$('sm-spool').required=false;
 let section='spoolman',smTab='spools';
 function show(key){section=key;saved.textContent='';for(const [k,p] of Object.entries(panes))p.hidden=k!==key;nav.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.settingsSection===key)));}
 function showSM(key){smTab=key;for(const [k,p] of Object.entries(smpanes))p.hidden=k!==key;tabs.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.smTab===key)));}
 function language(){const ru=currentLang==='ru',a=ru?['Принтер','Spoolman','Учёт','Резервная копия']:['Printer','Spoolman','Accounting','Backup'];nav.querySelectorAll('button').forEach((b,i)=>b.textContent=a[i]);tabs.querySelectorAll('button').forEach((b,i)=>b.textContent=(ru?['Подключение','Катушки','Передача расхода']:['Connection','Spools','Usage delivery'])[i]);h.textContent=ru?'Автоматический учёт':'Automatic accounting';save.textContent=ru?'Сохранить настройки учёта':'Save accounting settings';title.textContent=ru?'Назначение катушки':'Spool assignment';label.textContent=ru?'Головка принтера':'Toolhead';detach.textContent=ru?'Отвязать от Tracker':'Detach from Tracker';refresh.textContent=ru?'Обновить каталог':'Refresh catalog';}
 window.showTrackerSpoolmanSettings=()=>{show('spoolman');showSM('spools');};
 new MutationObserver(language).observe($('nav-settings'),{childList:true});language();show(section);showSM(smTab);
})();
</script>'''
def install(html):
    return html.replace('</body>', STYLE+SCRIPT+'</body>')
