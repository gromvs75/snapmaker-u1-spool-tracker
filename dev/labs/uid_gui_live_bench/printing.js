async page=>{
 await page.reload();const card=page.locator('[data-printer="warehouse"] [data-spool="manual-a"]');
 await card.getByRole('button',{name:'Перенести',exact:true}).waitFor();
 if(!await card.getByRole('button',{name:'Перенести',exact:true}).isDisabled())throw Error('printing permits transfer');
 const result=await page.evaluate(async()=>{const s=await api('state'),a=s.manual_assignments.find(a=>a.spool_id==='manual-a');try{await api('transfer',{spool_id:a.spool_id,source_printer:'a',source_channel:'0',target_printer:'b',target_channel:'2',expected_version:a.version,request_id:'active-reject',confirmed:true});throw Error('unsafe transfer accepted')}catch(e){if(!e.message.includes('Печать активна'))throw e;return {error:e.message,jobs:s.jobs.length}}});
 await page.screenshot({path:'/Users/viktor/snapmaker-tracker/output/uid-gui-live-bench/printing.png'});
 return {checks:['GUI blocks active spool','API blocks active printer'],result};
}
