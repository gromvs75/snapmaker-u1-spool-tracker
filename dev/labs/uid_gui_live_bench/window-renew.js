async page=>{
 await page.getByRole('button',{name:'Разрешить задание',exact:true}).click();await page.locator('#stoppedAck').check();await page.locator('#lossAck').check();await page.locator('#resolveSubmit').click();await page.locator('#resolveDialog').waitFor({state:'hidden'});
 for(const id of ['a','b']){const card=page.locator(`[data-printer="${id}"] [data-spool="manual-${id}"]`);await card.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.locator('#ack').check();await page.locator('#submit').click();await page.locator('#dialog').waitFor({state:'hidden'});}
 for(const [from,to,head] of [['a','b','2'],['b','a','0']]){await page.locator(`[data-printer="${from}"] [data-spool="manual-a"]`).dragTo(page.locator(`[data-printer="${to}"]`));await page.locator('#head').selectOption(head);await page.locator('#ack').check();await page.locator('#submit').click();await page.locator(`[data-printer="${to}"] [data-spool="manual-a"]`).waitFor();}
 const s=await page.evaluate(()=>api('state')),w=s.jobs.find(j=>j.unlock).unlock;
 if(!w.completed||w.revision!==2||s.resolutions.length!==1||s.debits.length!==3)throw Error('renewal result');
 await page.screenshot({path:'/Users/viktor/snapmaker-tracker/output/uid-unlock-live-bench/window-confirmed.png'});
 return {checks:['renewal creates second window revision','reconfirmation completes window','transfers after renewal keep balances','one permanent resolution and three debits'],window:w};
}
