import pytest
from storage import Store, ValidationError
from spool_tracker import WebHandler


def handler():
    h = object.__new__(WebHandler)
    h.path = '/api/spools/add'
    return h


def body(**extra):
    return dict(name='New spool', material='PLA', remaining_g=500, color='#00aa88', **extra)


def test_create_assign_is_single_store_update(tmp_path):
    store = Store(tmp_path, legacy_paths=())
    sid = store.update(lambda db: handler()._change(db, body(assign_slot='2', expected_slot='')))
    db = store.read()
    assert db['slots']['2'] == sid
    assert db['spools'][sid]['remaining_g'] == 500
    assert db['slots']['1'] == ''


@pytest.mark.parametrize('extra', [dict(assign_slot='5', expected_slot=''), dict(assign_slot='1', expected_slot='changed'), dict(assign_slot=None)])
def test_invalid_or_stale_assignment_creates_nothing(tmp_path, extra):
    store = Store(tmp_path, legacy_paths=())
    before = store.read()
    with pytest.raises(ValidationError):
        store.update(lambda db: handler()._change(db, body(**extra)))
    assert store.read() == before


def test_printing_blocks_combined_action(tmp_path):
    store = Store(tmp_path, legacy_paths=())
    store.update(lambda db: db['monitor'].update(state='printing'))
    with pytest.raises(ValidationError):
        store.update(lambda db: handler()._change(db, body(assign_slot='1', expected_slot='')))
    assert store.read()['spools'] == {}


def test_plain_create_still_leaves_heads_alone(tmp_path):
    store = Store(tmp_path, legacy_paths=())
    sid = store.update(lambda db: handler()._change(db, body()))
    assert sid in store.read()['spools']
    assert set(store.read()['slots'].values()) == {''}
