"""Snorca post-processing compatibility, using the single 2.0 writer.

An export is a provisional plan, never evidence of printing or consumption.
The active collector still verifies its actual file and mapping at print start.
"""
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('Local instance redirected')


def instance_call(directory, operation, data):
    descriptor=json.loads((Path(directory)/'instance.json').read_text())
    port=descriptor['port'];token=descriptor['token']
    if type(port) is not int or not 1<=port<=65535 or not isinstance(token,str) or len(token)<32:
        raise ValueError('Invalid instance descriptor')
    url=f'http://127.0.0.1:{port}/api/'+operation
    request=Request(url,data=json.dumps(data).encode(),headers={'Content-Type':'application/json','X-Tracker-Token':token})
    with build_opener(ProxyHandler({}),NoRedirect()).open(request,timeout=5) as reply:
        return json.loads(reply.read(1_000_000))


def describe(path, output_name=None):
    from gcode import parse_u1_gcode_handle
    path=Path(path).resolve()
    with path.open('rb') as handle:
        before=os.fstat(handle.fileno());weights=parse_u1_gcode_handle(handle)
        handle.seek(0);digest=hashlib.sha256()
        for chunk in iter(lambda:handle.read(1024*1024),b''):digest.update(chunk)
        after=os.fstat(handle.fileno())
    current=path.stat()
    if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns) or (after.st_ino,after.st_size,after.st_mtime_ns)!=(current.st_ino,current.st_size,current.st_mtime_ns):
        raise ValueError('G-code изменился во время проверки. Повторите экспорт.')
    return dict(filename=Path(output_name or path.name).name,file_sha256=digest.hexdigest(),
                weights=weights,source=str(path),completed_at_ns=after.st_mtime_ns)


def handle_slicer_hook(directory, path, *, output_name=None, dialog=None):
    from tracker_uid_session import Session
    from tracker_uid_catalog import CatalogBusyError
    from tracker_user_dialog import export_dialog
    dialog=dialog or export_dialog
    session=None
    try:
        plan=describe(path,output_name)
        try:
            # No workers, no automatic printer/Spoolman connections.
            session=Session(directory,allowed_urls=[])
            call=lambda operation,data:session.call(operation,**data)
        except CatalogBusyError:
            call=lambda operation,data:instance_call(directory,operation,data)
        preview=call('export_preview',{'plan':plan})
        lines=['Расход по материалам проекта. Привязка к головкам проверяется при запуске печати.']
        for material in preview['forecast']['materials']:
            grams = f"{material['grams']:.4f}".rstrip('0').rstrip('.').replace('.', ',')
            lines.append(f"Материал {material['number']} · {grams} г")
        if not dialog('\n'.join(lines),allow_proceed=True):return 1
        call('export_save',dict(plan=plan,expected_revision=preview['revision'],confirmed=True))
        return 0
    except (ValueError,OSError,KeyError,TimeoutError) as exc:
        dialog('Не удалось сохранить план экспорта: '+str(exc),allow_proceed=False)
        return 1
    finally:
        if session:session.close()
