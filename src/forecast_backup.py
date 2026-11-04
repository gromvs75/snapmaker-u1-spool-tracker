"""Backup bridge restricted to an explicitly supplied forecast lab Store."""
from pathlib import Path
from backup import parse_backup, write_backup
from storage import empty_db
from spool_tracker import normalize_dialog_path


class ForecastBackupBridge:
    def __init__(self, store, webview, directory):
        self._store = store
        self._webview = webview
        self._directory = Path(directory)
        self.window = None

    def hide(self):
        self.window.hide()

    def export_backup(self):
        selected = normalize_dialog_path(self.window.create_file_dialog(
            self._webview.FileDialog.SAVE, directory=str(self._directory),
            save_filename='TrackerForecastLab-backup.json', file_types=('JSON backup (*.json)',)))
        if not selected:
            return {'status': 'cancelled'}
        path = write_backup(self._store, selected, '1.2-alpha-forecast-lab')
        return {'status': 'ok', 'path': str(path)}

    def import_backup(self):
        selected = normalize_dialog_path(self.window.create_file_dialog(
            self._webview.FileDialog.OPEN, directory=str(self._directory),
            file_types=('JSON backup (*.json)',)))
        if not selected:
            return {'status': 'cancelled'}
        restored = parse_backup(selected)
        # Imported configuration must never enable a real printer in this lab.
        restored['printer'] = empty_db()['printer']
        restored['monitor'] = empty_db()['monitor']
        safety = self._store.replace_snapshot(restored)
        return {'status': 'ok', 'safety_backup': str(safety)}
