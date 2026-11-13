// Phase 1, then wait for GUI_READY phase2 in the runner log before phase 2.
async page => {
 await page.goto('http://127.0.0.1:18898');
 await page.locator('#navSettings').click();
 await page.getByRole('button',{name:'Отправки',exact:true}).click();
 await page.locator('#deliveryList button').first().click();
 await page.getByRole('button',{name:'Прочитать состояние Spoolman',exact:true}).click();
 if(!await page.locator('#deliverySave').isDisabled())throw Error('Missing confirmation');
 await page.locator('#deliveryDecision').selectOption('applied');
 await page.locator('#deliveryNote').fill('Isolated proxy log proves applied PUT followed by lost response.');
 await page.locator('#deliveryAck').check();
 await page.locator('#deliverySave').click();
 return 'phase1 saved; runner verifies no new HTTP';
}
