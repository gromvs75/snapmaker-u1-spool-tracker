"""End-to-end browser tests of Tracker's real dashboard and HTTP/WS sender."""
import json
from pathlib import Path
import time

import pytest
pytest.importorskip('websockets')
playwright = pytest.importorskip('playwright.sync_api')
from playwright.sync_api import expect
from dev.sender_dashboard_demo import Demo


@pytest.fixture(scope='module')
def browser():
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def page_for(browser, demo):
    context = browser.new_context(viewport={'width':1280, 'height':960})
    page = context.new_page()
    page.goto(demo.url)
    page.get_by_role('button', name='Отправка', exact=True).click()
    expect(page.locator('#sender-status')).to_have_text('Выберите файл')
    return context, page


def select_check(page, demo):
    page.locator('#sender-file').set_input_files(str(demo.fixture))
    expect(page.locator('#sender-status')).to_have_text('Файл выбран')
    page.get_by_role('button', name='Проверить файл', exact=True).click()
    expect(page.locator('#sender-status')).to_have_text('Проверка пройдена')


def upload(page):
    page.get_by_role('button', name='Загрузить без запуска').click()
    expect(page.locator('#sender-status')).to_have_text('Файл загружен и проверен')


def start(page):
    page.get_by_role('button', name='Запустить на тестовом сервере').click()
    page.get_by_role('button', name='Подтвердить запуск', exact=True).click()


def test_complete_browser_flow(browser, tmp_path):
    with Demo(tmp_path) as demo:
        before = demo.store.path.read_bytes()
        context, page = page_for(browser, demo)
        errors=[]
        page.on('pageerror', lambda e: errors.append(str(e)))
        try:
            expect(page.locator('#sender-upload')).to_be_disabled()
            expect(page.locator('#sender-start')).to_be_disabled()
            select_check(page, demo)
            assert demo.mock.uploads == demo.mock.start_requests == []
            expect(page.locator('#sender-report')).to_contain_text('15 г')
            page.screenshot(path='/tmp/tracker-sender-ui-checked.png', full_page=True)
            # An edited mapping invalidates UI permission until checked again.
            page.locator('#sender-map-0').select_option('1')
            expect(page.locator('#sender-upload')).to_be_disabled()
            page.locator('#sender-map-0').select_option('0')
            page.locator('#sender-check').click()
            expect(page.locator('#sender-status')).to_have_text('Проверка пройдена')
            upload(page)
            assert len(demo.mock.uploads)==1 and not demo.mock.start_requests
            page.locator('#sender-start').click()
            page.get_by_role('button', name='Отмена', exact=True).click()
            assert not demo.mock.start_requests
            start(page)
            expect(page.locator('#sender-status')).to_have_text('Запуск подтверждён')
            assert len(demo.mock.uploads)==len(demo.mock.accepted_starts)==1
            page.reload()
            page.get_by_role('button', name='Отправка', exact=True).click()
            expect(page.locator('#sender-status')).to_have_text('Запуск подтверждён')
            expect(page.locator('#sender-start')).to_be_disabled()
            replay = context.request.post(demo.url+'/api/sender/start', data={'confirmed':True})
            assert replay.status==400
            assert len(demo.mock.accepted_starts)==1
            assert demo.store.path.read_bytes()==before
            assert not errors
        finally:
            context.close()


def test_browser_denial_has_no_network_write(browser, tmp_path):
    with Demo(tmp_path) as demo:
        demo.store.update(lambda db: db['spools']['s0'].update(remaining_g=1))
        context,page=page_for(browser,demo)
        try:
            page.locator('#sender-file').set_input_files(str(demo.fixture))
            expect(page.locator('#sender-status')).to_have_text('Файл выбран')
            page.locator('#sender-check').click()
            expect(page.locator('#sender-status')).to_have_text('Проверка или отправка заблокирована')
            expect(page.locator('#sender-report')).to_contain_text('Требует внимания')
            expect(page.locator('#sender-upload')).to_be_disabled()
            assert not demo.mock.uploads and not demo.mock.start_requests
        finally: context.close()


def test_browser_timeout_is_persistent_and_no_retry(browser,tmp_path):
    with Demo(tmp_path, fault='start_timeout', timeout=.2) as demo:
        context,page=page_for(browser,demo)
        try:
            select_check(page,demo); upload(page); start(page)
            expect(page.locator('#sender-status')).to_have_text('Исход запуска неизвестен')
            assert len(demo.mock.accepted_starts)==1
            from dev.labs.sender_dashboard import SenderDashboard
            recovered = SenderDashboard(demo.controller.directory, demo.store.path, demo.mock.http_url, demo.mock.ws_url, .2)
            demo.server.RequestHandlerClass.sender_controller = recovered
            page.reload();page.get_by_role('button', name='Отправка', exact=True).click()
            expect(page.locator('#sender-status')).to_have_text('Исход запуска неизвестен')
            expect(page.locator('#sender-file')).to_be_disabled()
            expect(page.locator('#sender-start')).to_be_disabled()
            result=context.request.post(demo.url+'/api/sender/start',data={'confirmed':True})
            assert result.status==400 and len(demo.mock.start_requests)==1
            page.screenshot(path='/tmp/tracker-sender-ui-timeout.png',full_page=True)
        finally:context.close()


def test_changed_inventory_after_upload_blocks_start(browser,tmp_path):
    with Demo(tmp_path) as demo:
        context,page=page_for(browser,demo)
        try:
            select_check(page,demo); upload(page)
            demo.store.update(lambda db: db['spools']['s0'].update(remaining_g=0))
            start(page)
            expect(page.locator('#sender-status')).to_have_text('Запуск заблокирован')
            assert len(demo.mock.uploads)==1 and not demo.mock.start_requests
        finally:context.close()


def test_server_requires_check_origin_and_confirmation(browser,tmp_path):
    with Demo(tmp_path) as demo:
        context,page=page_for(browser,demo)
        try:
            assert context.request.post(demo.url+'/api/sender/upload',data={}).status==400
            assert context.request.post(demo.url+'/api/sender/check',data={},headers={'Origin':'https://example.com'}).status==403
            select_check(page,demo);upload(page)
            assert context.request.post(demo.url+'/api/sender/start',data={}).status==400
            assert not demo.mock.start_requests
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
            page.screenshot(path='/tmp/tracker-sender-ui-mobile.png',full_page=True)
        finally:context.close()


def test_invalid_file_shows_persistent_error(browser,tmp_path):
    with Demo(tmp_path) as demo:
        context,page=page_for(browser,demo)
        try:
            page.locator('#sender-file').set_input_files({'name':'bad.txt','mimeType':'text/plain','buffer':b'bad'})
            expect(page.locator('#sender-status')).to_have_text('Действие не выполнено')
            expect(page.locator('#sender-help')).to_contain_text('.gcode')
            expect(page.locator('#sender-upload')).to_be_disabled()
            assert not demo.mock.uploads and not demo.mock.start_requests
        finally:context.close()


def test_checker_error_ui_blocks_actions(browser,tmp_path,monkeypatch):
    from dev.labs import sender_dashboard
    def fail(*args,**kwargs):
        raise TimeoutError('Checker timeout')
    monkeypatch.setattr(sender_dashboard,'strict_check',fail)
    with Demo(tmp_path) as demo:
        context,page=page_for(browser,demo)
        try:
            page.locator('#sender-file').set_input_files(str(demo.fixture))
            expect(page.locator('#sender-status')).to_have_text('Файл выбран')
            page.locator('#sender-check').click()
            expect(page.locator('#sender-status')).to_have_text('Проверка или отправка заблокирована')
            expect(page.locator('#sender-upload')).to_be_disabled()
            assert not demo.mock.uploads and not demo.mock.start_requests
        finally:context.close()
