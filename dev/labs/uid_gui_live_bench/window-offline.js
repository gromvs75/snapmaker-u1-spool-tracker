async page=>{
 await page.reload();await page.locator('[data-printer="a"] .warning').getByText('Нет связи — перенос недоступен',{exact:true}).waitFor();
 const result=await page.evaluate(async()=>{const s=await api('state');let rejected=false;try{await api('resolve',JSON.parse(sessionStorage.getItem('unlockPayload')))}catch(e){rejected=true}return {s,rejected}});
 if(!result.rejected||result.s.debits.length!==3||!result.s.printers.find(p=>p.id==='b').ready)throw Error('offline isolation');
 await page.screenshot({path:'/Users/viktor/snapmaker-tracker/output/uid-unlock-live-bench/window-offline.png'});
 return {checks:['offline resolution rejected by live reader','second printer stays ready','outage creates no debit']};
}
