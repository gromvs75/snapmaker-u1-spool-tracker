"""Disposable macOS menu-bar prototype. No real paths, settings or network.

Every launch makes a fresh synthetic watch directory. The installed Tracker,
its Store, printer monitor and sender are deliberately not imported.
"""
import copy
import json
from pathlib import Path
import queue
import tempfile
import threading

from slice_observer import SliceObserver, ForecastAttention

STOCK = (100, 50, 25, 110)


def forecast_text(entry):
    if not entry:
        return 'Ожидаем завершённую нарезку в тестовом каталоге.'
    state = entry['state']
    if state != 'ready':
        return ('Результат удалён. Прогноз недоступен.' if state == 'removed' else
                'Файл ещё записывается или не прошёл проверку.\nПрогноз недоступен; предыдущий расчёт скрыт.')
    import datetime
    stamp = datetime.datetime.fromtimestamp(entry['observed_at']).strftime('%H:%M:%S')
    lines = ['Последний завершённый результат · ' + stamp,
             'Назначение физических головок: неизвестно.', '',
             'Условный расчёт при соответствии T0→T0, T1→T1…',
             'Только тестовые остатки; резерв 5 г на используемую катушку.', '',
             'Канал     Нужно      Остаток     После печати   С резервом']
    shortage = False
    for i, used in enumerate(entry['weights']):
        enough = STOCK[i] >= used + (5 if used else 0)
        shortage |= not enough
        lines.append('T%d     %7.2f г   %7.2f г   %9.2f г   %s' %
                     (i, used, STOCK[i], STOCK[i] - used, 'хватит' if enough else 'НЕ ХВАТИТ'))
    lines += ['', 'При этом назначении: ' + ('есть нехватка.' if shortage else 'запаса достаточно.'),
              '', 'Это оценка расхода, а не разрешение на печать.',
              'Выбранная пластина и изменения модели в Snorca неизвестны.']
    return '\n'.join(lines)


def main(real_slice_lab=False, gui_slice_lab=False):
    import objc
    import AppKit as A
    from Foundation import NSObject
    from PyObjCTools import AppHelper

    if real_slice_lab and gui_slice_lab:
        raise ValueError('Choose one isolated lab mode')
    if gui_slice_lab:
        root = Path('/tmp/tracker-gui-slice-lab').resolve(strict=True)
        if (root / 'GUI_SLICE_LAB_ONLY').read_text() != 'offline-gui-only\n':
            raise RuntimeError('Missing isolated GUI-slice lab marker')
        watch = root / 'tmp' / 'snapmaker_orca_model'
        watch.mkdir(exist_ok=True)
    elif real_slice_lab:
        root = Path('/tmp/tracker-real-slice-lab').resolve(strict=True)
        if (root / 'REAL_SLICE_LAB_ONLY').read_text() != 'offline-cli-only\n':
            raise RuntimeError('Missing isolated real-slice lab marker')
        watch = root / 'output'
    else:
        root = Path(tempfile.mkdtemp(prefix='tracker-observer-lab-'))
        (root / 'OBSERVER_LAB_ONLY').write_text('synthetic-only\n')
        watch = root / 'slices'
        watch.mkdir()
    observer = SliceObserver(watch, layout='cli' if real_slice_lab else 'snorca')
    updates = queue.Queue()
    stop = threading.Event()

    def worker():
        while not stop.is_set():
            try:
                events = observer.poll()
                updates.put((copy.deepcopy(observer.entries), events, None))
            except Exception as exc:
                updates.put(({}, [], str(exc)))
            controller.performSelectorOnMainThread_withObject_waitUntilDone_('tick:', None, False)
            stop.wait(.3)

    class Controller(NSObject):
        def setup(self):
            self.entries = {}
            self.selected = None
            self.attention = ForecastAttention(self.reveal)
            self.popup_events = []
            self.window = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                A.NSMakeRect(0, 0, 860, 580),
                A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable | A.NSWindowStyleMaskMiniaturizable,
                A.NSBackingStoreBuffered, False)
            title = ('Tracker GUI Slice Lab' if gui_slice_lab else
                     'Tracker Real Slice Lab' if real_slice_lab else 'Tracker Observer Lab')
            self.window.setTitle_(title + ' · Прогноз нарезки')
            self.window.setReleasedWhenClosed_(False)
            self.window.center()
            view = self.window.contentView()

            def label(text, frame, size):
                field = A.NSTextField.labelWithString_(text)
                field.setFrame_(A.NSMakeRect(*frame))
                field.setFont_(A.NSFont.systemFontOfSize_(size))
                view.addSubview_(field)
                return field

            label('Прогноз после нарезки', (24, 528, 810, 34), 25)
            banner = ('ИЗОЛИРОВАННЫЙ СТЕНД · Кнопка Slice в GUI Snorca · Тестовые катушки' if gui_slice_lab else
                      'ИЗОЛИРОВАННЫЙ СТЕНД · Настоящая CLI-нарезка Snorca · Тестовые катушки' if real_slice_lab else
                      'ИЗОЛИРОВАННЫЙ СТЕНД · Только искусственные файлы и катушки')
            label(banner, (24, 496, 810, 25), 13)
            self.select = A.NSPopUpButton.alloc().initWithFrame_pullsDown_(A.NSMakeRect(24, 452, 810, 32), False)
            self.select.setTarget_(self)
            self.select.setAction_('selection:')
            view.addSubview_(self.select)
            self.body = A.NSTextView.alloc().initWithFrame_(A.NSMakeRect(24, 96, 810, 342))
            self.body.setEditable_(False)
            self.body.setFont_(A.NSFont.userFixedPitchFontOfSize_(13))
            self.body.setDrawsBackground_(False)
            view.addSubview_(self.body)
            self.footer = label('Окно появится автоматически после готового результата.', (24, 64, 810, 24), 12)
            for text, action, x in [('Скрыть в строку меню', 'hide:', 24), ('Завершить стенд', 'quit:', 650)]:
                button = A.NSButton.alloc().initWithFrame_(A.NSMakeRect(x, 18, 185, 32))
                button.setTitle_(text)
                button.setBezelStyle_(A.NSBezelStyleRounded)
                button.setTarget_(self)
                button.setAction_(action)
                view.addSubview_(button)
            self.item = A.NSStatusBar.systemStatusBar().statusItemWithLength_(A.NSVariableStatusItemLength)
            self.item.button().setTitle_('Tracker Lab ◌')
            self.item.button().setTarget_(self)
            self.item.button().setAction_('show:')
            self.render()
            # Start hidden: the producer completing a result, not launch, reveals it.

        def render(self):
            keys = sorted(self.entries)
            self.select.removeAllItems()
            self.select.addItemsWithTitles_(keys or ['Нет результатов'])
            if self.selected not in keys:
                self.selected = keys[0] if keys else None
            if self.selected:
                self.select.selectItemWithTitle_(self.selected)
            self.body.setString_(forecast_text(self.entries.get(self.selected)))

        def selection_(self, sender):
            self.selected = str(self.select.titleOfSelectedItem())
            self.body.setString_(forecast_text(self.entries.get(self.selected)))

        @objc.python_method
        def reveal(self, events):
            self.selected = events[-1]['source']
            self.popup_events.append([{'source': e['source'], 'sha256': e['sha256']} for e in events])
            self.render()
            self.show_(None)

        def show_(self, sender):
            self.window.deminiaturize_(None)
            self.window.makeKeyAndOrderFront_(None)
            A.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

        def hide_(self, sender):
            self.window.orderOut_(None)

        def quit_(self, sender):
            stop.set()
            AppHelper.stopEventLoop()

        def tick_(self, timer):
            while not updates.empty():
                entries, events, error = updates.get_nowait()
                if entries != self.entries:
                    self.entries = entries
                    self.render()
                if error:
                    self.body.setString_('Наблюдатель остановил обработку: ' + error)
                self.attention.accept(events)
            ready = sum(e['state'] == 'ready' for e in self.entries.values())
            self.item.button().setTitle_('Tracker Lab · %d' % ready)
            self.footer.setStringValue_('Готовых результатов: %d · Автопоказов: %d · Выбранный файл не означает активную пластину Snorca' % (ready, self.attention.batches))
            report = {'root': str(root), 'entries': self.entries, 'popup_batches': self.attention.batches,
                      'popup_events': self.popup_events, 'window_visible': bool(self.window.isVisible()),
                      'selected': self.selected, 'stock': STOCK}
            tmp = root / 'report.tmp'
            tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            tmp.replace(root / 'report.json')

    app = A.NSApplication.sharedApplication()
    app.setActivationPolicy_(A.NSApplicationActivationPolicyAccessory)
    app.finishLaunching()
    controller = Controller.alloc().init()
    controller.setup()
    controller.tick_(None)
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    print(json.dumps({'root': str(root)}), flush=True)
    try:
        AppHelper.runEventLoop()
    finally:
        stop.set()
        thread.join(timeout=3)
    return 0


if __name__ == '__main__':
    main()
