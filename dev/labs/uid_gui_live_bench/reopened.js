async page=>{
 await page.reload();const card=page.locator('[data-printer="b"] [data-spool="manual-b"]');
 await card.getByText('Нужно подтверждение',{exact:true}).waitFor();
 const s=await page.evaluate(()=>api('state'));
 if(s.debits.length!==3||s.spools.find(s=>s.spool_id==='manual-a').remaining_mg!==499702||s.spools.find(s=>s.spool_id==='manual-b').remaining_mg!==299404)throw Error('replay changed balance');
 await card.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.locator('#ack').check();await page.locator('#submit').click();await card.getByText('Назначение подтверждено',{exact:true}).waitFor();
 return {checks:['reopened database keeps exact balances','history replay has three debits','manual reconfirmation works after owner restart']};
}
