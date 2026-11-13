async page=>{
 await page.reload();await page.getByRole('button',{name:'Разрешить задание',exact:true}).waitFor();
 const card=page.locator('[data-printer="a"] [data-spool="manual-a"]');
 if(!await card.getByRole('button',{name:'Подтвердить',exact:true}).isDisabled()||!await card.getByRole('button',{name:'Перенести',exact:true}).isDisabled())throw Error('expired UI permits assignment');
 const result=await page.evaluate(async()=>{const p=JSON.parse(sessionStorage.getItem('unlockPayload')),original=JSON.parse(sessionStorage.getItem('originalWindow'));await api('resolve',p);const s=await api('state'),w=s.jobs.find(j=>j.unlock).unlock;let denied=false;const a=s.manual_assignments.find(a=>a.spool_id==='manual-a');try{await api('assign',{printer_id:'a',channel:'0',spool_id:a.spool_id,expected_version:a.version,confirmed:true})}catch(e){denied=e.message.includes('истекло')}return {w,original,denied,debits:s.debits.length}});
 if(!result.w.expired||result.w.deadline!==result.original.deadline||!result.denied||result.debits!==3)throw Error('expired replay or API bypass');
 await page.screenshot({path:'/Users/viktor/snapmaker-tracker/output/uid-unlock-live-bench/window-expired.png'});
 return {checks:['expired UI relocks after reconnect and owner restart','old replay preserves original deadline','API rejects confirmation after expiry','no debit across expiry'],window:result.w};
}
