"""Read-only background integration for the main application on macOS/Windows."""
import logging
from pathlib import Path
import tempfile
import threading

from forecast import ForecastState
from slice_observer import SliceObserver


def default_slice_root():
    # Snorca's default backup root is below the OS/user temporary directory.
    # A custom Snorca backup path can be supplied with --slice-root.
    return Path(tempfile.gettempdir()) / 'snapmaker_orca_model'


class ForecastService:
    def __init__(self, store, on_change, root=None):
        self.root = Path(root) if root is not None else default_slice_root()
        self.state = ForecastState(store=store)
        self.on_change = on_change
        self.observer = None
        self.stop_event = threading.Event()
        self.thread = None
        self.updates = 0

    def poll(self):
        if not self.root.is_dir():
            return []  # Snorca may start later. Never create its directories.
        if self.observer is None:
            self.observer = SliceObserver(self.root)
        events = self.observer.poll()
        self.state.accept(events)
        if events:
            self.on_change()
            self.updates += 1
        return events

    def snapshot(self):
        result = self.state.snapshot()
        result['watch_root'] = str(self.root)
        result['auto_shows'] = 0  # Compatibility: slicing never opens a window.
        result['updates'] = self.updates
        monitor = self.state.store.read().get('monitor', {})
        # Preserve print-start figures on the head cards throughout an active job,
        # including a temporary disconnect. Forecast remains in its own card.
        result['printing'] = monitor.get('state') in ('printing', 'paused')
        return result

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.poll()
            except Exception:
                logging.getLogger('snapmaker_tracker').exception('Slice observer failed')
                with self.state.lock:
                    self.state.error = 'Slice observer unavailable'
            self.stop_event.wait(1)

    def start(self):
        self.thread = threading.Thread(target=self._run, name='slice-forecast', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
