async page => {
 await page.goto('http://127.0.0.1:18773');
 await page.setViewportSize({width:1202,height:950});
 await page.locator('[data-printer="a"] .card').filter({hasText:'RFID A'}).waitFor();
 await page.locator('[data-printer="b"] .card').filter({hasText:'RFID B'}).waitFor();
 const labels=await page.locator('.card .status').allTextContents();
 if(!labels.every(x=>x==='Распознана по RFID'))throw Error(JSON.stringify(labels));
 await page.locator('#navSettings').click();
 await page.getByRole('button',{name:'Остановить подключения',exact:true}).click();
 await page.getByRole('button',{name:'Подключить принтеры',exact:true}).click();
 await page.locator('#navHeads').click();
 await page.locator('[data-printer="a"] .card .status').filter({hasText:'Распознана по RFID'}).waitFor();
 return {passed:true,checks:['two RFID cards rendered','RFID recognized labels','GUI stops unified services','GUI starts unified services','RFID returns after reconnect']};
}
