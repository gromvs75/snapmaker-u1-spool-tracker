"""Read-only, explicit-root Snorca slice observer. No printer or Store imports.

Internal v2.4.1 non-BBL format only. A forecast is evidence of a completed
file, never evidence that this is the currently selected/unedited GUI plate.
"""
import hashlib
import os
from pathlib import Path
import re
import stat
import time

from gcode import GCodeError, METADATA, parse_slice_usage
from slice_bed_marker import embedded_bed_identity

FILAMENT_CONFIG = re.compile(r'^;\s*filament_(colour|type)\s*=\s*(.*?)\s*$', re.IGNORECASE)
HEX_COLOUR = re.compile(r'#[0-9a-fA-F]{6}')
NAME = re.compile(r'^\.[0-9]+\.[0-9]+\.gcode$')
MAX_BYTES = 128 * 1024 * 1024


def fingerprint(st):
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def read_snapshot(path):
    """Bounded read; reject symlinks, special files, replacements and mutations."""
    before_path = path.lstat()
    if not stat.S_ISREG(before_path.st_mode) or path.is_symlink():
        raise GCodeError('Unsupported file type')
    flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    fd = os.open(str(path), flags)
    with os.fdopen(fd, 'rb') as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES or fingerprint(before) != fingerprint(before_path):
            raise GCodeError('Unsupported file or size')
        content = handle.read(MAX_BYTES + 1)
        after = os.fstat(handle.fileno())
    if (len(content) != before.st_size or fingerprint(before) != fingerprint(after)
            or fingerprint(after) != fingerprint(path.lstat())):
        raise GCodeError('File changed during read')
    return content, fingerprint(after)


def completed_materials(content, *, allow_extra_profiles=False):
    text = content.decode('utf-8', errors='strict')
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # Non-BBL Snorca writes the final config block after executable + usage.
    # The rename from .gcode.tmp is the producer's commit; these checks also
    # reject truncated/corrupt files written directly to a final pathname.
    markers = ['; EXECUTABLE_BLOCK_START', '; EXECUTABLE_BLOCK_END',
               '; CONFIG_BLOCK_START', '; CONFIG_BLOCK_END']
    if not text.endswith('\n') or not lines or lines[-1] != markers[-1]:
        raise GCodeError('No complete footer')
    if any(lines.count(marker) != 1 for marker in markers):
        raise GCodeError('Missing or ambiguous blocks')
    positions = [lines.index(marker) for marker in markers]
    if positions != sorted(positions):
        raise GCodeError('Invalid block order')
    weights = [i for i, line in enumerate(lines) if METADATA.match(line)]
    if len(weights) != 1 or not positions[1] < weights[0] < positions[2]:
        raise GCodeError('Missing or ambiguous usage')
    usage = parse_slice_usage(lines[weights[0]], allow_extra_profiles=allow_extra_profiles)
    fields = {'colour': [], 'type': []}
    for line in lines[positions[2] + 1:positions[3]]:
        match = FILAMENT_CONFIG.match(line)
        if match:
            fields[match[1].lower()].append(match[2])
    raw_colors = fields['colour'][0].split(';') if len(fields['colour']) == 1 else []
    colors = [color if HEX_COLOUR.fullmatch(color) else None for color in map(str.strip, raw_colors)]
    types = fields['type'][0].split(';') if len(fields['type']) == 1 else []
    return usage, colors, types


class SliceObserver:
    def __init__(self, root, settle_seconds=1.0, clock=time.monotonic, layout='snorca', *, allow_extra_profiles=False):
        if layout not in ('snorca', 'cli'):
            raise ValueError('Unsupported observer layout')
        self.layout = layout
        self.allow_extra_profiles = allow_extra_profiles
        self.root = Path(root).resolve(strict=True)
        self.settle = settle_seconds
        self.clock = clock
        self.entries = {}
        self._candidates = {}
        self._notified = {}  # Last announced content per source, not global hash.

    def _paths(self):
        result = {}
        for directory, dirs, files in os.walk(self.root, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(directory) / d).is_symlink()]
            if self.layout == 'snorca' and Path(directory).name != 'Metadata':
                continue
            if self.layout == 'cli' and Path(directory) != self.root:
                continue
            for name in files:
                final = name[:-4] if name.endswith('.tmp') else name
                matches = NAME.fullmatch(final) if self.layout == 'snorca' else re.fullmatch(r'plate_[1-9][0-9]*\.gcode', final)
                if matches:
                    path = Path(directory) / final
                    result[str(path.relative_to(self.root))] = path
        return result

    def poll(self):
        """Return a batch of new previews; mutable entries also expose pending states."""
        now = self.clock()
        paths = self._paths()
        events = []
        for key in self.entries.keys() - paths.keys():
            self.entries[key] = {'source': key, 'state': 'removed'}
            self._candidates.pop(key, None)
        for key, path in sorted(paths.items()):
            try:
                if Path(str(path) + '.tmp').exists():
                    raise GCodeError('Slicing temporary file exists')
                previous = self.entries.get(key, {})
                candidate = self._candidates.get(key)
                if (previous.get('state') == 'ready' and candidate
                        and fingerprint(path.lstat()) == candidate[0][0]):
                    continue
                content, signature = read_snapshot(path)
                digest = hashlib.sha256(content).hexdigest()
                identity = (signature, digest)
                if not candidate or candidate[0] != identity:
                    self._candidates[key] = (identity, now)
                    self.entries[key] = {'source': key, 'state': 'pending'}
                    continue
                if now - candidate[1] < self.settle:
                    continue
                weights, colors, types = completed_materials(content, allow_extra_profiles=self.allow_extra_profiles)
                plate, plate_identity = embedded_bed_identity(content)
                preview = {'source': key, 'state': 'ready', 'sha256': digest,
                           'weights': weights, 'colors': colors, 'filament_types': types, 'completed_at_ns': signature[3],
                           'plate': plate, 'plate_identity': plate_identity,
                           'observed_at': previous.get('observed_at', time.time()) if previous.get('sha256') == digest else time.time(),
                           'mapping': 'unknown'}
                self.entries[key] = preview
                if self._notified.get(key) != digest:
                    self._notified[key] = digest
                    events.append(dict(preview))
            except (OSError, ValueError) as exc:
                self._candidates.pop(key, None)
                self.entries[key] = {'source': key, 'state': 'pending', 'reason': str(exc)}
        return events


class ForecastAttention:
    """One popup per poll batch, not one popup per plate; no popup for pending."""
    def __init__(self, reveal):
        self.reveal = reveal
        self.batches = 0

    def accept(self, events):
        if events:
            self.reveal(events)
            self.batches += 1
