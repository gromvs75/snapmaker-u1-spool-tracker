"""Read the live Snapmaker Orca preprint selection, for display only."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPException
import json
import math
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit
from uuid import UUID


PREPRINT_PATH = '/web/flutter_web/prepare_print'
MAX_CONTEXT_BYTES = 8 * 1024 * 1024
MATERIAL_BUTTON = re.compile(r'.+?\s+(\d+(?:[.,]\d+)?)\s*g\s+([1-4])', re.IGNORECASE)


def preprint_address(url):
    # Accept only Orca's native preprint page on its IPv4 loopback gateway.
    if url.startswith('127.0.0.1:'):
        url = 'http://' + url
    try:
        parts = urlsplit(url)
        context_ids = parse_qs(parts.query, max_num_fields=16).get('id', [])
        if (parts.scheme != 'http' or parts.netloc != f'127.0.0.1:{parts.port}'
                or not parts.port or parts.path != PREPRINT_PATH or len(context_ids) != 1):
            return None
        return parts.port, str(UUID(context_ids[0]))
    except ValueError:
        return None


def load_context(address):
    port, context_id = address
    # No redirects or proxies. Keep only the fields used to join the slice.
    connection = HTTPConnection('127.0.0.1', port, timeout=0.3)
    try:
        connection.request('GET', '/api/store/' + context_id, headers={'Connection': 'close'})
        response = connection.getresponse()
        if response.status != 200:
            return None
        data = response.read(MAX_CONTEXT_BYTES + 1)
        if len(data) > MAX_CONTEXT_BYTES:
            return None
        payload = json.loads(data)
        return payload.get('data', payload) if isinstance(payload, dict) else None
    except (OSError, HTTPException, ValueError):
        return None
    finally:
        connection.close()


def clean(label):
    return ' '.join(label.split())


def dialog_selection(nodes):
    """Read only the printer button and the selected buttons in filament order."""
    printer_buttons = []
    labeled_printer_buttons = []
    materials = []
    section = ''
    for role, labels in nodes:
        if role in ('AXStaticText', 'AXHeading') and 'Configure Filaments' in labels:
            section = 'materials'
        if role in ('AXStaticText', 'AXHeading') and 'Print Preferences' in labels:
            if section == 'materials':
                return tuple(labeled_printer_buttons or printer_buttons), tuple(materials)
        if role not in ('AXButton', 'AXPopUpButton'):
            continue
        if not section:
            names = tuple(
                name.removeprefix('Select Printer ').removesuffix(' Lan Mode')
                for name in labels if name != 'Select Printer'
            )
            if names:
                printer_buttons.append(names)
                if any(label.startswith('Select Printer ') or label == 'Select Printer' for label in labels):
                    labeled_printer_buttons.append(names)
        else:
            matches = {m.groups() for label in labels if (m := MATERIAL_BUTTON.fullmatch(label))}
            if not matches and (match := MATERIAL_BUTTON.fullmatch(' '.join(labels))):
                matches.add(match.groups())
            if len(matches) == 1:
                amount, head = matches.pop()
                amount = amount.replace(',', '.')
                precision = len(amount.partition('.')[2])
                materials.append((float(amount), precision, str(int(head) - 1)))
    return (), ()


@dataclass(frozen=True)
class PreprintSelection:
    printer_id: str
    source: str
    sha256: str
    # None means the dialog is bound to this slice but its selections are unresolved.
    channels: dict | None


def match_selection(context, nodes, root, entries, printers):
    if not isinstance(context, dict):
        return None
    mapping = context.get('filament_mapping')
    active_file = context.get('active_file')
    if not isinstance(mapping, dict) or not isinstance(active_file, dict):
        return None
    path = context.get('file_path')
    checksum = active_file.get('checksum')
    if not isinstance(path, str) or active_file.get('file_path') != path or not isinstance(checksum, str):
        return None
    try:
        source = str(Path(path).resolve(strict=True).relative_to(root.resolve(strict=True)))
        digest = base64.b64decode(checksum, validate=True).hex()
    except (OSError, RuntimeError, ValueError):
        return None
    entry = next((e for e in entries if e['source'] == source and e['state'] == 'ready'
                  and e.get('sha256') == digest), None)
    if entry is None:
        return None

    buttons, materials = dialog_selection(nodes)
    # One selected device button. Match its name only when inventory resolves it uniquely.
    if len(buttons) != 1:
        return None
    names = {label.casefold() for label in buttons[0]}
    printer_ids = {pid for pid, printer in printers.items()
                   if any(clean(printer.get(key) or '').casefold() in names
                          for key in ('name', 'configured_name'))}
    if len(printer_ids) != 1:
        return None
    pid = printer_ids.pop()
    selection = PreprintSelection(pid, source, digest, None)
    weights = entry['weights']
    exact = mapping.get('filament_weight')
    if (not isinstance(exact, list) or len(exact) > 32
            or any(type(w) not in (int, float) or not 0 <= w <= 1_000_000 for w in exact)):
        return selection
    if any(exact[4:]) or any(weights[4:]):
        return selection

    # The 2.4.1 dialog iterates the used base filaments in source order.
    # Color mixes have already been resolved into these filaments in the G-code.
    logical = [(i, w) for i, w in enumerate(exact) if w > 0]
    if len(logical) != len(materials) or not logical:
        return selection
    if any(not math.isclose(w, exact[i] if i < len(exact) else 0, rel_tol=0, abs_tol=.005001)
           for i, w in enumerate(weights)):
        return selection
    channels = {}
    for (i, w), (amount, precision, channel) in zip(logical, materials):
        if not math.isclose(w, amount, rel_tol=0, abs_tol=0.5 * 10 ** -precision + 1e-6):
            return selection
        if i < len(weights) and weights[i] > 0:
            channels[i + 1] = channel
    if set(channels) != {i + 1 for i, w in enumerate(weights) if w > 0}:
        return selection
    return PreprintSelection(pid, source, digest, channels)


class OrcaPreprint:
    def __init__(self, reader, context_loader=load_context):
        self.reader = reader
        self.context_loader = context_loader
        self.address = None
        self.context = None

    def read(self, root, entries, printers):
        document = self.reader()
        address = preprint_address(document[0]) if document else None
        if address != self.address:
            self.address = address
            self.context = None
        if address is None:
            return None
        if self.context is None:
            self.context = self.context_loader(address)
        return match_selection(self.context, document[1], root, entries, printers)
