async page => {
 const checks=[];const check=(n,v)=>{if(!v)throw Error(n);checks.push(n)};
 await page.goto('http://127.0.0.1:18749');await page.setViewportSize({width:1202,height:1000});
 for(const id of ['manual-a']){
  const card=page.locator(`[data-printer="warehouse"] [data-spool="${id}"]`);
  await card.getByRole('button',{name:'Подтвердить',exact:true}).click();
  check('confirmation requires checkbox '+id,await page.locator('#submit').isDisabled());
  await page.locator('#ack').check();await page.locator('#submit').click();
  await card.getByText('Назначение подтверждено',{exact:true}).waitFor();
 }
 let replay;
 for(const [from,to,head] of [['a','b','2'],['b','a','0']]){
  await page.locator(`[data-printer="${from}"] [data-spool="manual-a"]`).dragTo(page.locator(`[data-printer="${to}"]`));
  check('drop selects destination '+to,await page.locator('#printer').inputValue()===to);
  if(to==='b')check('occupied T1 disabled',await page.locator('#head option[value="1"]').isDisabled());
  await page.locator('#head').selectOption(head);
  replay=await page.evaluate(()=>({spool_id:selection.spool.spool_id,source_printer:selection.assignment.printer_id,source_channel:selection.assignment.channel,target_printer:document.getElementById('printer').value,target_channel:document.getElementById('head').value,expected_version:selection.assignment.version,request_id:selection.request_id,confirmed:true}));
  await page.locator('#ack').check();await page.locator('#submit').click();
  await page.locator(`[data-printer="${to}"] [data-spool="manual-a"]`).waitFor();
 }
 const repeated=await page.evaluate(p=>api('transfer',p),replay);
 check('replayed GUI transfer returns same location',repeated.printer_id==='a'&&repeated.channel==='0');
 const state=await page.evaluate(()=>api('state'));
 check('no debit from transfer',state.debits.length===0);
 await page.screenshot({path:'/Users/viktor/snapmaker-tracker/output/uid-gui-live-bench/idle-reconnected.png'});
 return {checks,state};
}
