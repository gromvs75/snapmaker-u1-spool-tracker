import copy
import time

import pytest

from spoolman_bridge import Bridge, blank, remote_id, label_comparison, validate
from storage import Store
from dev.labs.spoolman_compare.demo import CatalogFixture, URL


@pytest.fixture
def comparison(tmp_path):
    store = Store(tmp_path / 'inventory', legacy_paths=())
    fixture = CatalogFixture()
    bridge = Bridge(store, lambda url: fixture)
    bridge.configure(URL, 'read')
    bridge.attach(2, 0)
    sid = remote_id(URL, 2)
    store.update(lambda db: db['spools'][sid].update(name='[Spoolman #2] RAPID PETG Green'))
    return store, bridge, fixture, sid


def test_compare_is_read_only_and_exposes_both_names(comparison):
    store, bridge, fixture, sid = comparison
    before = store.read()
    row = bridge.label_comparison()['rows'][0]
    assert row['tracker_name'] == '[Spoolman #2] RAPID PETG Green'
    assert row['canonical_name'] == '[Spoolman #2] ELEGOO RAPID PETG Green'
    assert row['manufacturer'] == 'ELEGOO'
    assert row['available'] and not row['matches']
    assert store.read() == before


def test_sync_changes_only_name_even_during_print_with_pending_usage(comparison):
    store, bridge, fixture, sid = comparison
    def pending(db):
        db['monitor']['state'] = 'printing'
        db['spoolman']['outbox']['test-op'] = {'job': 'j', 'local_id': sid, 'url': URL,
            'spool_id': 2, 'grams': 2., 'created_at': time.time(), 'state': 'pending'}
    store.update(pending)
    before = store.read()
    row = bridge.label_comparison()['rows'][0]
    bridge.sync_label(sid, row['revision'])
    expected = copy.deepcopy(before)
    expected['spools'][sid]['name'] = row['canonical_name']
    assert store.read() == expected
    assert bridge.label_comparison()['rows'][0]['matches']


@pytest.mark.parametrize('change', ['name', 'catalog', 'epoch', 'url', 'deleted', 'archived', 'expired', 'off', 'error'])
def test_stale_or_unavailable_comparison_cannot_apply(comparison, change):
    store, bridge, fixture, sid = comparison
    revision = bridge.label_comparison()['rows'][0]['revision']
    def alter(db):
        if change == 'name': db['spools'][sid]['name'] = 'Changed independently'
        if change == 'catalog': db['spoolman']['catalog']['2']['name'] = 'Changed at source'
        if change == 'epoch': db['spoolman']['epoch'] = 'new-epoch'
        if change == 'url': db['spoolman']['url'] = 'http://localhost:1234'
        if change == 'deleted': del db['spoolman']['catalog']['2']
        if change == 'archived': db['spoolman']['catalog']['2']['archived'] = True
        if change == 'expired': db['spoolman']['checked_at'] = time.time()-61
        if change == 'off': db['spoolman']['mode'] = 'off'
        if change == 'error': db['spoolman']['error'] = 'Offline'
    store.update(alter)
    before = store.read()
    with pytest.raises(ValueError): bridge.sync_label(sid, revision)
    assert store.read() == before


def test_refresh_comparison_does_not_apply_labels_or_balances(comparison):
    store, bridge, fixture, sid = comparison
    before = store.read()
    original = fixture.catalog
    def changed():
        catalog = original()
        catalog['2'].update(remaining_g=20, name='ELEGOO New label')
        return catalog
    fixture.catalog = changed
    bridge.refresh_label_catalog()
    after = store.read()
    assert after['spools'] == before['spools']
    assert after['slots'] == before['slots']
    assert after['runs'] == before['runs']
    assert after['spoolman']['outbox'] == before['spoolman']['outbox']
    row = bridge.label_comparison()['rows'][0]
    bridge.sync_label(sid, row['revision'])
    assert store.read()['spools'][sid]['remaining_g'] == before['spools'][sid]['remaining_g']


def test_failed_refresh_disables_sync(comparison):
    store, bridge, fixture, sid = comparison
    revision = bridge.label_comparison()['rows'][0]['revision']
    def failure(): raise OSError('Simulated offline')
    fixture.catalog = failure
    with pytest.raises(ValueError): bridge.refresh_label_catalog()
    with pytest.raises(ValueError): bridge.sync_label(sid, revision)


def test_empty_and_old_cached_catalogs_are_supported(comparison):
    store, bridge, fixture, sid = comparison
    db = store.read()
    del db['spoolman']['catalog']['2']['manufacturer']
    del db['spoolman']['catalog']['2']['filament_name']
    assert label_comparison(db)['rows'][0]['manufacturer'] == ''
    db['spools'] = {}
    assert label_comparison(db)['rows'] == []
    assert validate(blank()) == blank()


def test_sync_cannot_target_local_spool_or_inject_custom_name(comparison):
    store, bridge, fixture, sid = comparison
    store.update(lambda db: db['spools'].update(local={'name': 'Local', 'material': 'PLA', 'remaining_g': 100}))
    before = store.read()
    with pytest.raises(ValueError): bridge.sync_label('local', 'invalid')
    with pytest.raises(ValueError): bridge.sync_label(sid, None)
    assert store.read() == before
