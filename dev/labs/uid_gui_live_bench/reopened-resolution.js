async page=>{
 await page.reload();const card=page.locator('[data-printer="b"] [data-spool="manual-b"]');
 await card.getByText('Нужно подтверждение',{exact:true}).waitFor();
 const s=await page.evaluate(()=>api('state'));
 if(s.debits.length!==4||s.spools.find(s=>s.spool_id==='manual-a').remaining_mg!==499404||s.spools.find(s=>s.spool_id==='manual-b').remaining_mg!==299404)throw Error('replay changed balance');
 await card.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.locator('#ack').check();await page.locator('#submit').click();await card.getByText('Назначение подтверждено',{exact:true}).waitFor();
 if(s.resolutions.length!==1)throw Error('resolution receipt lost');
 return {checks:['reopened database keeps exact balances','history replay has four debits','manual reconfirmation works after owner restart']};
}
