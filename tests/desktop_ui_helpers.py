"""Explicit acceptance for fixture tests previously accepting OS confirmations."""
def accept_graphite_confirmations(page):
    page.add_init_script('''
      document.addEventListener('DOMContentLoaded', () => {
        new MutationObserver(() => {
          document.querySelector('#graphite-confirm-dialog[open] #graphite-confirm-apply')?.click();
        }).observe(document.body, {childList:true, subtree:true});
      });
    ''')


def audit_dialog(page, name):
    from pathlib import Path
    out=Path('output/remaining-dialogs');out.mkdir(parents=True,exist_ok=True)
    d=page.locator('dialog[open]').last
    d.wait_for(state='visible')
    assert d.locator('.gd-header,.gs-header').count()==1, name
    for width in (945,480):
        page.set_viewport_size({'width':width,'height':850})
        assert d.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1'), name
        footer=d.locator('.gd-footer,.gs-footer')
        if footer.is_visible():
            assert footer.bounding_box()['y']+footer.bounding_box()['height']<=850, name
    page.set_viewport_size({'width':945,'height':850})
    page.screenshot(path=str(out/(name+'.png')),full_page=True)
