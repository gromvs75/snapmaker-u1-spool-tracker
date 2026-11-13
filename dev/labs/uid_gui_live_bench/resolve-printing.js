async page=>{
 await page.reload();await page.locator('[data-printer="a"]').getByRole('button',{name:'Разрешить задание',exact:true}).click();
 if(!await page.locator('#resolveSubmit').isDisabled())throw Error('unchecked resolution enabled');
 await page.locator('#stoppedAck').check();
 if(!await page.locator('#resolveSubmit').isDisabled())throw Error('loss acknowledgement not required');
 await page.locator('#lossAck').check();await page.locator('#resolveSubmit').click();
 await page.locator('#resolveError').getByText('Принтер печатает или приостановлен. Сначала остановите печать.',{exact:true}).waitFor();
 const s=await page.evaluate(()=>api('state'));
 if(s.resolutions.length||s.debits.length!==3)throw Error('printing resolution mutated accounting');
 await page.screenshot({path:'/Users/viktor/snapmaker-tracker/output/uid-resolution-live-bench/resolve-printing.png'});
 await page.locator('#resolveCancel').click();
 return {checks:['two acknowledgements required','fresh live print_stats rejects printing','rejected resolution leaves no receipt or debit']};
}
