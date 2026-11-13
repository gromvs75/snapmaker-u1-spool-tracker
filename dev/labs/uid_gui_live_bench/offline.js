async page=>{
 await page.reload();await page.locator('[data-printer="a"] .warning').getByText('Нет связи — перенос недоступен',{exact:true}).waitFor();
 await page.locator('[data-printer="b"] [data-spool="manual-b"]').dragTo(page.locator('[data-printer="a"]'));
 await page.locator('#ack').check();if(!await page.locator('#submit').isDisabled())throw Error('offline target enabled');
 await page.locator('#cancel').click();
 const state=await page.evaluate(()=>api('state'));
 if(state.debits.length!==3)throw Error('unaffected printer debit missing');
 if(state.manual_assignments.find(a=>a.printer_id==='a').confirmed)throw Error('offline confirmation remained valid');
 await page.screenshot({path:'/Users/viktor/snapmaker-tracker/output/uid-gui-live-bench/offline.png'});
 return {checks:['offline warning visible','offline drop cannot submit','manual trust invalidated','other printer debit visible'],balances:state.spools,debits:state.debits.length};
}
