"""Native backup dialogs bound only to a sender lab's explicit Store."""
from pathlib import Path

from backup import parse_backup, write_backup
from storage import empty_db
from spool_tracker import normalize_dialog_path


class LabBackupBridge:
    def __init__(self, demo, webview):
        self._demo = demo
        self._webview = webview
        self.window = None

    def export_backup(self):
        selected = normalize_dialog_path(self.window.create_file_dialog(
            self._webview.FileDialog.SAVE, directory=str(self._demo.root),
            save_filename='TrackerSenderLab-backup.json', file_types=('JSON backup (*.json)',)))
        if not selected:
            return {'status': 'cancelled'}
        path = write_backup(self._demo.store, selected, '1.2-alpha-lab')
        return {'status': 'ok', 'path': str(path)}

    def import_backup(self):
        controller = self._demo.controller
        def require_idle():
            if controller.busy or controller.draft['state'] not in ('empty', 'selected', 'checked', 'blocked'):
                raise ValueError('Импорт заблокирован: текущее задание не завершено. Повтор запуска запрещён.')
        with controller.lock:
            require_idle()
        selected = normalize_dialog_path(self.window.create_file_dialog(
            self._webview.FileDialog.OPEN, directory=str(self._demo.root),
            file_types=('JSON backup (*.json)',)))
        if not selected:
            return {'status': 'cancelled'}
        restored = parse_backup(Path(selected))
        # A lab import cannot arm printer monitoring, even from a real backup.
        restored['printer'] = empty_db()['printer']
        restored['monitor'] = empty_db()['monitor']
        with controller.lock:
            require_idle()  # The dialog may have been open while a sender action ran.
            safety = self._demo.store.replace_snapshot(restored)
            if controller.draft.get('request'):
                controller.draft['state'] = 'selected'
                controller.draft['rows'] = []
                controller.draft['reason'] = 'После импорта нужна новая проверка.'
                controller._save()
        return {'status': 'ok', 'safety_backup': str(safety)}
