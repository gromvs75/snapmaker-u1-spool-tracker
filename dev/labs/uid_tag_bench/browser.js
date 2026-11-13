// Run while run.py --browser waits; then create output/tag-live/go.
async page => {
 await page.goto('http://127.0.0.1:18783');
 await page.setViewportSize({width:1202,height:950});
 await page.locator('[data-printer="a"] .tag-card button').click();
 await page.locator('#tagDialog[open]').waitFor();
 await page.locator('#tagName').fill('RFID A');
 await page.locator('#tagMaterial').fill('PLA');
 await page.locator('#tagMass').fill('500');
 if(!await page.locator('#tagSave').isDisabled())throw Error('Missing physical confirmation');
 await page.locator('#tagAck').check();
 await page.locator('#tagSave').click();
 await page.locator('#tagDialog').waitFor({state:'hidden'});
 await page.locator('[data-printer="b"] .tag-card button').click();
 await page.locator('#tagDialog[open]').waitFor();
 await page.locator('#tagMode').selectOption('existing');
 await page.locator('#tagSpool').selectOption('existing-b');
 if(await page.locator('#tagMass').isEnabled())throw Error('Existing balance editable');
 await page.locator('#tagAck').check();
 await page.locator('#tagSave').click();
 await page.locator('#tagDialog').waitFor({state:'hidden'});
 return {notice:await page.locator('#notice').innerText(),cards:await page.locator('[data-printer="b"] .card').allTextContents()};
}
