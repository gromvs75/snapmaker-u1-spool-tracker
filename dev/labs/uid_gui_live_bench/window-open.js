async page=>{
 await page.reload();await page.getByRole('button',{name:'Разрешить задание',exact:true}).click();
 const payload=await page.evaluate(()=>({job_key:resolutionSelection.job_key,expected_version:resolutionSelection.resolution_version,confirmed:true,accept_unaccounted:true,mode:'15_minutes'}));
 await page.evaluate(p=>sessionStorage.setItem('unlockPayload',JSON.stringify(p)),payload);
 await page.locator('#stoppedAck').check();await page.locator('#lossAck').check();await page.locator('#resolveSubmit').click();await page.locator('#resolveDialog').waitFor({state:'hidden'});
 const s=await page.evaluate(()=>api('state')),w=s.jobs.find(j=>j.unlock).unlock;
 if(w.completed||w.expired||w.mode!=='15_minutes'||s.debits.length!==3)throw Error('window initial state');
 await page.evaluate(w=>sessionStorage.setItem('originalWindow',JSON.stringify(w)),w);
 return {checks:['15 minute window opens through GUI','pending window creates no extra debit'],window:w};
}
