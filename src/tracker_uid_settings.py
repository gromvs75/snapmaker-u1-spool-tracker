"""Explicit printer endpoints; persistent IDs survive renames and reconnects."""
import re
from urllib.parse import urlsplit,urlunsplit
from tracker_uid_client import PrinterEndpoint


def validate_printers(printers):
    if not isinstance(printers,list) or len(printers)>32:raise ValueError('Допускается до 32 принтеров.')
    result=[]
    for p in printers:
        if not isinstance(p,dict) or set(p)!={'id','name','url'}:raise ValueError('Неверные поля принтера.')
        if not isinstance(p['id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',p['id']):raise ValueError('Неверный постоянный ID.')
        if not isinstance(p['name'],str) or not p['name'].strip() or len(p['name'])>100:raise ValueError('Укажите имя принтера.')
        if not isinstance(p['url'],str) or len(p['url'])>2048:raise ValueError('Неверный адрес Moonraker.')
        u=urlsplit(p['url'].strip())
        PrinterEndpoint(p['id'],p['name'],p['url'].strip()).websocket_url()
        port=u.port or (443 if u.scheme=='https' else 80)
        host=u.hostname.lower()
        if ':' in host:host='['+host+']'
        url=urlunsplit((u.scheme,host+((':'+str(port)) if port!=(443 if u.scheme=='https' else 80) else ''),u.path.rstrip('/'),'',''))
        result.append(dict(id=p['id'],name=p['name'].strip(),url=url))
    if len({p['id'] for p in result})!=len(result) or len({p['url'] for p in result})!=len(result):
        raise ValueError('ID и адрес каждого принтера должны быть уникальными.')
    return result
