"""Sender dashboard controller; explicit test endpoints and inventory only."""
import base64
import json
from pathlib import Path
import threading
import uuid

from presend import decode_json, digest, evaluate
from sender import Ledger, LocalTransport, MAX_FILE, send, start_uploaded, strict_check


class SenderDashboard:
    def __init__(self, directory, inventory_path, http, ws, timeout=2):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.inventory = Path(inventory_path)
        self.transport = LocalTransport(http, ws, timeout)
        self.ledger = Ledger(self.directory / 'sender.sqlite')
        self.path = self.directory / 'draft.json'
        self.lock = threading.RLock()
        self.busy = False
        self.draft = decode_json(self.path.read_bytes()) if self.path.exists() else {'state': 'empty'}
        if self.draft.get('request'):
            entry = self.ledger.get(self.draft['request']['request_id'])
            if entry:
                self.draft['state'] = entry['state']
                self.draft['reason'] = entry['reason']
            elif self.draft['state'] in ('checking','uploading','starting'):
                self.draft['state'] = 'selected'
        self._save()

    def _save(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.draft, ensure_ascii=False), encoding='utf-8')
        temporary.replace(self.path)

    def status(self):
        with self.lock:
            return {'enabled': True, 'state': self.draft['state'], 'busy': self.busy,
                    'filename': self.draft.get('filename', ''), 'rows': self.draft.get('rows', []),
                    'reason': self.draft.get('reason', ''), 'endpoint': self.transport.http,
                    'mapping': self.draft.get('request', {}).get('mapping', [0,1,2,3])}

    def select(self, body):
        with self.lock:
            if self.busy or self.draft['state'] not in ('empty','selected','checked','blocked','sent'):
                raise ValueError('Resolve the current job before selecting another file')
            name = body.get('filename', '')
            if not isinstance(name, str) or not name.lower().endswith('.gcode') or len(name) > 240:
                raise ValueError('Select a .gcode file')
            data = base64.b64decode(body.get('content', ''), validate=True)
            if not data or len(data) > MAX_FILE:
                raise ValueError('G-code must be between 1 byte and 32 MiB')
            job_id = uuid.uuid4().hex
            file = self.directory / (job_id + '.gcode')
            file.write_bytes(data)
            self.draft = {'state': 'selected', 'filename': name, 'rows': [], 'reason': '',
                'request': {'version':1, 'request_id':job_id, 'context_id':job_id, 'device_id':'TEST-U1',
                            'action':'send','mapping':[0,1,2,3], 'gcode_path':str(file),
                            'inventory_path':str(self.inventory), 'sha256':digest(data)}}
            self._save()
            return self.status()

    def action(self, name, body):
        with self.lock:
            permitted = {'check': ('selected','checked','blocked'), 'upload': ('checked',), 'start': ('sent',)}
            if self.busy or self.draft['state'] not in permitted.get(name, ()):
                raise ValueError('Action is unavailable for this job')
            if name == 'start' and body.get('confirmed') is not True:
                raise ValueError('Explicit start confirmation required')
            if name == 'check':
                from tool_mapping import validate_mapping
                mapping = body.get('mapping')
                if not isinstance(mapping, list) or len(mapping) != 4:
                    raise ValueError('Four mapping entries required')
                validate_mapping(mapping)
                # A fresh check after a blocked attempt needs a new operation identity.
                if self.ledger.get(self.draft['request']['request_id']):
                    self.draft['request']['request_id'] = uuid.uuid4().hex
                self.draft['request']['mapping'] = mapping
            self.busy = True
            self.draft['state'] = {'check':'checking','upload':'uploading','start':'starting'}[name]
            self.draft['reason'] = ''
            self._save()
            threading.Thread(target=self._work, args=(name,), daemon=True).start()
            return self.status()

    def _work(self, name):
        try:
            request = dict(self.draft['request'])
            if name == 'check':
                # Show policy rows even on denial; bounded subprocess is authoritative.
                response = evaluate(request)
                rows = response['rows']
                for row, material in zip(rows, response['materials']):
                    row['material_status'] = material['status']
                with self.lock:
                    self.draft['rows'] = rows
                strict_check(request, self.transport.timeout)
                result = {'state':'checked'}
            elif name == 'upload':
                result = send(request, self.transport, self.ledger, checker_timeout=self.transport.timeout)
            else:
                result = start_uploaded(request['request_id'], self.transport, self.ledger, checker_timeout=self.transport.timeout)
        except Exception as exc:
            result = {'state': {'check':'blocked', 'upload':'upload_unknown', 'start':'outcome_unknown'}[name], 'reason':str(exc)}
        with self.lock:
            self.draft['state'] = result['state']
            self.draft['reason'] = result.get('reason','')
            self.busy = False
            self._save()
