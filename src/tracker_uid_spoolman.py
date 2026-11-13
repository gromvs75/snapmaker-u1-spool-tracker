"""Released 1.3.3 catalog normalization and read-only transport for UID UI."""
import json
import math
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError

def endpoint(value):
    if not isinstance(value, str):
        raise ValueError('Spoolman URL required')
    p = urlsplit(value.strip())
    if (p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password
            or p.query or p.fragment or any(c.isspace() for c in value)
            or p.path.rstrip('/').endswith('/api/v1')):
        raise ValueError('Use the server base URL without credentials, query or /api/v1')
    _ = p.port
    return value.strip().rstrip('/')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Spoolman redirects are not supported; use its final address')


class Client:
    def __init__(self, url):
        self.url = endpoint(url)
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, method, path, body=None):
        req = Request(self.url + '/api/v1' + path,
                      data=None if body is None else json.dumps(body, allow_nan=False).encode(),
                      headers={'Content-Type': 'application/json'}, method=method)
        try:
            with self.opener.open(req, timeout=5) as response:
                raw = response.read(8_000_001)
                if len(raw) > 8_000_000:
                    raise ValueError('Spoolman response too large')
                return json.loads(raw), response.headers
        except HTTPError as exc:
            # Never include response bodies, credentials or the server URL in errors.
            raise ValueError('Spoolman HTTP %d' % exc.code) from None

    def catalog(self):
        info, _ = self.request('GET', '/info')
        if info.get('version') != '0.27.1':
            raise ValueError('This test build supports Spoolman 0.27.1 only')
        result = {}
        for offset in range(0, 10000, 100):
            rows, headers = self.request('GET', '/spool?allow_archived=true&limit=100&offset=%d' % offset)
            if not isinstance(rows, list):
                raise ValueError('Invalid spool catalog')
            for row in rows:
                item = catalog_item(row)
                if str(item['id']) in result:
                    raise ValueError('Catalog changed during paging; refresh again')
                result[str(item['id'])] = item
            total = headers.get('X-Total-Count')
            if len(rows) < 100 or (total is not None and len(result) >= int(total)):
                return result
        raise ValueError('Catalog exceeds 10000 spools')


def number(value):
    if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
        raise ValueError('Invalid Spoolman weight')
    return float(value)


def catalog_item(row):
    if not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] <= 0:
        raise ValueError('Invalid Spoolman spool ID')
    f = row.get('filament', {})
    name = str(f.get('name') or 'Spool').strip() or 'Spool'
    vendor = f.get('vendor')
    brand = vendor.get('name') if isinstance(vendor, dict) else None
    brand = brand.strip() if isinstance(brand, str) else ''
    # Spoolman stores the manufacturer separately from the filament name.
    # Some catalogs already include it; preserve those names without repetition.
    if brand and not (name.casefold() == brand.casefold()
                      or name.casefold().startswith(brand.casefold() + ' ')):
        name = brand + ' ' + name
    color = f.get('color_hex', '')
    remaining = row.get('remaining_weight')
    return {'id': row['id'], 'name': name[:100],
            'manufacturer': brand[:100], 'filament_name': str(f.get('name') or 'Spool')[:100],
            'material': str(f.get('material') or 'Unknown')[:100],
            'remaining_g': None if remaining is None else number(remaining),
            'archived': bool(row.get('archived', False)),
            'color': '#' + color.lower() if len(color) == 6 and all(c in '0123456789abcdefABCDEF' for c in color) else None}

