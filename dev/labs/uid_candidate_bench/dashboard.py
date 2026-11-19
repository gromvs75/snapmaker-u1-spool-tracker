"""Exercise the new dashboard in the EXE's actual embedded WebView2 page."""
from playwright.sync_api import expect


def verify(page, request, printer, out):
    def event(state,**values):request(printer+'/event',dict(action='telemetry',state=state,**values))
    page.locator('#nav-overview').click()
    event('printing')
    expect(page.locator('.dash-percent')).to_have_text('62%',timeout=15000)
    expect(page.locator('#dashboard-elapsed')).to_have_text('3 ч 18 мин')
    expect(page.locator('#dashboard-remaining')).to_have_text('2 ч 2 мин')
    expect(page.locator('#sidebar-slots .sidebar-slot')).to_have_count(4)
    expect(page.locator('#sidebar-slots .selected-head .dash-head-stripe')).to_contain_text('T1')
    sources=page.locator('#dashboard-sources')
    expect(sources.locator('[data-source=connection]')).to_contain_text('есть связь')
    expect(sources.locator('[data-source=head] .dash-source-badge')).to_have_text('T1')
    sources.locator('[data-source=rfid] summary').click()
    page.wait_for_timeout(1200)
    assert sources.locator('[data-source=rfid]').get_attribute('open') is not None
    page.evaluate('window.scrollTo(0, 0)')
    page.wait_for_timeout(150)
    page.screenshot(path=str(out/'dashboard-native-printing.png'),full_page=True)
    sources.locator('[data-source=rfid] summary').click()
    event('paused')
    expect(page.locator('#overview-connection')).to_have_text('Пауза',timeout=15000)
    expect(page.locator('#dashboard-finish')).to_have_text('—')
    expect(page.locator('.dash-active')).to_have_count(0)
    event('complete')
    expect(page.locator('.dash-percent')).to_have_text('100%',timeout=15000)
    event('printing',known=False)
    expect(page.locator('.dash-percent')).to_have_text('—',timeout=15000)
    expect(page.locator('#dashboard-remaining')).to_have_text('—')
    event('standby',filename='')
    expect(page.locator('#overview-connection')).to_have_text('Ожидание',timeout=15000)
    expect(sources.locator('[data-source=head] .dash-source-badge')).to_have_text('неизвестно')
    page.evaluate('window.scrollTo(0, 0)')
    page.wait_for_timeout(150)
    page.screenshot(path=str(out/'dashboard-native-idle.png'),full_page=True)
    return 'dashboard: embedded page shows progress, ETA, T0–T3, active T1, expandable sources, pause/complete/unknown/idle'
