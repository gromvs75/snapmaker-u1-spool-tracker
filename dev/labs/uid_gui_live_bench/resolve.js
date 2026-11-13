async page=>{
 const checks=[];const check=(n,v)=>{if(!v)throw Error(n);checks.push(n)};
 await page.reload();const open=()=>page.locator('[data-printer="a"]').getByRole('button',{name:'Разрешить задание',exact:true}).click();
 await open();await page.locator('#resolveCancel').click();
 check('cancel preserves reservation',(await page.evaluate(()=>api('state'))).resolutions.length===0);
 await open();check('acknowledgements reset',!await page.locator('#stoppedAck').isChecked()&&!await page.locator('#lossAck').isChecked());
 await page.screenshot({path:'/Users/viktor/snapmaker-tracker/output/uid-resolution-live-bench/resolve-dialog.png'});
 const payload=await page.evaluate(()=>({job_key:resolutionSelection.job_key,expected_version:resolutionSelection.resolution_version,confirmed:true,accept_unaccounted:true,mode:document.querySelector('[name=unlockMode]:checked').value}));
 const forged=await page.evaluate(async p=>{try{await api('resolve',{...p,observation:{state:'standby'}});return false}catch(e){return e.message.includes('Неверные параметры')}},payload);
 check('client cannot supply printer state',forged);
 const stale=await page.evaluate(async p=>{try{await api('resolve',{...p,expected_version:'stale'});return false}catch(e){return e.message.includes('изменилось')}},payload);
 check('stale decision rejected',stale);
 await page.locator('#stoppedAck').check();await page.locator('#lossAck').check();await page.locator('#resolveSubmit').click();
 await page.locator('#resolveDialog').waitFor({state:'hidden'});
 const repeat=await page.evaluate(p=>api('resolve',p),payload);
 check('repeat returns durable receipt',repeat.status==='resolved_without_debit');
 let s=await page.evaluate(()=>api('state'));
 check('one resolution and no new debit',s.resolutions.length===1&&s.debits.length===3);
 check('manual assignment needs renewed confirmation',!s.manual_assignments.find(a=>a.spool_id==='manual-a').confirmed);
 await page.locator('[data-printer="a"] [data-spool="manual-a"]').getByRole('button',{name:'Подтвердить',exact:true}).click();
 await page.locator('#ack').check();await page.locator('#submit').click();
 for(const [from,to,head] of [['a','b','2'],['b','a','0']]){
  await page.locator(`[data-printer="${from}"] [data-spool="manual-a"]`).dragTo(page.locator(`[data-printer="${to}"]`));
  await page.locator('#head').selectOption(head);await page.locator('#ack').check();await page.locator('#submit').click();
  await page.locator(`[data-printer="${to}"] [data-spool="manual-a"]`).waitFor();
 }
 s=await page.evaluate(()=>api('state'));
 check('transfer after resolution preserves balance',s.spools.find(s=>s.spool_id==='manual-a').remaining_mg===499702);
 await page.screenshot({path:'/Users/viktor/snapmaker-tracker/output/uid-resolution-live-bench/resolved.png'});
 return {checks,payload};
}
