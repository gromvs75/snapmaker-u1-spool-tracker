async page => {
 await page.getByRole('button',{name:'Обновить операции',exact:true}).click();
 await page.locator('#deliveryList button').first().click();
 await page.locator('#deliveryDecision').selectOption('not_applied');
 await page.locator('#deliveryNote').fill('Isolated proxy log proves request dropped before server.');
 await page.locator('#deliveryAck').check();
 await page.locator('#deliverySave').click();
 await page.locator('#deliveryList button').first().click();
 await page.locator('#deliverySendAck').check();
 await page.locator('#deliverySend').click();
 return 'phase2 explicitly sent; runner verifies one retry and final balance';
}
