"""Native file dialogs for 2.0 envelopes; JS supplies no filesystem paths."""
import json
from pathlib import Path
from tracker_uid_migration import atomic


class BackupFiles:
    def __init__(self, window, webview):
        self.window=window;self.webview=webview

    def __call__(self, action, package=None):
        window=self.window()
        if window is None:raise ValueError('Native window unavailable')
        save=action=='export'
        if action not in ('export','select'):raise ValueError('Invalid file action')
        selected=window.create_file_dialog(self.webview.SAVE_DIALOG if save else self.webview.OPEN_DIALOG,
            **dict(save_filename='tracker-2.0-backup.json') if save else dict(allow_multiple=False))
        if not selected:return {'status':'cancelled'}
        path=Path(selected if isinstance(selected,str) else selected[0])
        if save:
            atomic(path,json.dumps(package,ensure_ascii=False).encode())
            return dict(status='ok',path=str(path))
        with path.open('rb') as stream:raw=stream.read(46*1024*1024+1)
        if len(raw)>46*1024*1024:raise ValueError('Backup exceeds 46 MB')
        return dict(status='ok',package=json.loads(raw))
