async page=>{
 await page.reload();await page.locator('[data-printer="a"] .warning').getByText('Прерванное задание — перенос заблокирован',{exact:true}).waitFor();
 const s=await page.evaluate(()=>api('state'));
 if(!s.printers.every(p=>p.ready)||s.debits.length!==3||s.jobs.length!==4)throw Error('reconnect state incorrect');
 const card=page.locator('[data-printer="a"] [data-spool="manual-a"]');
 if(!await card.getByRole('button',{name:'Перенести',exact:true}).isDisabled())throw Error('uncertain capture unlocked');
 await page.screenshot({path:'/Users/viktor/snapmaker-tracker/output/uid-gui-live-bench/reconnected.png'});
 return {checks:['both printers reconnected','uncertain job clearly labelled','uncertain transfer remains blocked','no new capture or debit on reconnect']};
}
