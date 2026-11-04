from forecast_lab_app import ForecastState, STOCK


def entry(plate, grams, digest='first'):
    return {'source': f'session/Metadata/.123.{plate}.gcode', 'state': 'ready',
            'sha256': digest, 'weights': [grams, 0, 0, 0], 'observed_at': 1,
            'mapping': 'unknown'}


def test_repeated_slice_replaces_one_plate_without_debiting_inventory():
    state = ForecastState()
    state.accept([entry(0, 10), entry(1, 20)])
    state.accept([entry(0, 30, 'second')])
    snapshot = state.snapshot()
    assert len(snapshot['entries']) == 2
    assert snapshot['latest'].endswith('.0.gcode')
    assert snapshot['revision'] == 2
    assert snapshot['mapping_assumed'] is True
    first, second = snapshot['entries']
    assert first['rows'][0]['after'] == 70
    assert second['rows'][0]['after'] == 80
    assert first['rows'][0]['remaining'] == second['rows'][0]['remaining'] == STOCK[0]


def test_reserve_shortage_and_unused_head():
    state = ForecastState()
    state.accept([entry(0, 96)])
    result = state.snapshot()['entries'][0]
    assert result['shortage']
    assert result['rows'][0]['after'] == 4
    assert not result['rows'][0]['enough']
    assert result['rows'][1]['enough']


def test_no_completed_result_does_not_replace_last_completed_forecast():
    state = ForecastState()
    state.accept([entry(0, 10)])
    before = state.snapshot()
    state.accept([])
    assert state.snapshot() == before
    external = state.snapshot()
    external['entries'][0]['rows'][0]['remaining'] = -100
    assert state.snapshot() == before


def test_lab_stock_survives_new_state_without_debit(tmp_path):
    from forecast_lab_app import load_lab_stock
    (tmp_path / 'forecast-stock.json').write_text('{"stock_g": [5, 50, 25, 110]}')
    for _ in range(2):
        state = ForecastState(load_lab_stock(tmp_path))
        state.accept([entry(1, 8.97)])
        row = state.snapshot()['entries'][0]['rows'][0]
        assert row['remaining'] == 5
        assert row['after'] == -3.97
        assert not row['enough']


def test_invalid_lab_stock_rejected(tmp_path):
    import pytest
    from forecast_lab_app import load_lab_stock
    for invalid in ('[5]', '[true, 50, 25, 110]', '[-1, 50, 25, 110]', '[NaN, 50, 25, 110]'):
        (tmp_path / 'forecast-stock.json').write_text('{"stock_g": ' + invalid + '}')
        with pytest.raises(ValueError):
            load_lab_stock(tmp_path)


def test_live_store_edits_recalculate_without_slice_or_debit(tmp_path):
    from storage import Store
    store = Store(tmp_path / 'inventory', legacy_paths=())
    def seed(db):
        db['spools'] = {'a': {'name': 'Катушка A', 'material': 'PLA', 'remaining_g': 5},
                        'b': {'name': 'Катушка B', 'material': 'PLA', 'remaining_g': 50}}
        db['slots']['1'] = 'a'
        db['safety_margin_g'] = 5
    store.update(seed)
    state = ForecastState(store=store)
    state.accept([entry(1, 9)])
    original = store.path.read_bytes()
    assert state.snapshot()['entries'][0]['shortage']
    assert store.path.read_bytes() == original
    store.update(lambda db: db['spools']['a'].update(remaining_g=20))
    changed = store.path.read_bytes()
    result = state.snapshot()
    assert result['revision'] == 1
    assert result['entries'][0]['rows'][0]['after'] == 11
    assert not result['entries'][0]['shortage']
    assert store.path.read_bytes() == changed
    store.update(lambda db: db['slots'].update({'1': 'b'}))
    row = state.snapshot()['entries'][0]['rows'][0]
    assert row['name'] == 'Катушка B' and row['remaining'] == 50
    store.update(lambda db: db['slots'].update({'1': ''}))
    assert state.snapshot()['entries'][0]['shortage']
    assert state.snapshot()['entries'][0]['rows'][0]['name'] == 'Катушка не назначена'


def test_shared_spool_uses_combined_consumption():
    from forecast_lab_app import forecast_entry
    event = entry(0, 6)
    event['weights'] = [6, 6, 0, 0]
    inventory = {'slots': {'1': 'a', '2': 'a'},
                 'spools': {'a': {'name': 'Shared', 'remaining_g': 10}}, 'safety_margin_g': 0}
    result = forecast_entry(event, inventory=inventory)
    assert result['shortage']
    assert result['rows'][0]['after'] == result['rows'][1]['after'] == -2


def test_latest_project_uses_completion_time_not_discovery_order():
    def event(project, plate, stamp):
        e = entry(plate, 3)
        e['source'] = f'{project}/Metadata/.123.{plate}.gcode'
        e['completed_at_ns'] = stamp
        return e
    state = ForecastState()
    state.accept([event('z-old', 0, 10), event('a-new', 0, 20), event('z-old', 1, 11)])
    assert state.snapshot()['project'] == 'a-new'
    assert len(state.snapshot()['entries']) == 1
    state.accept([event('z-old', 2, 12)])  # delayed discovery must not select an old project
    assert state.snapshot()['project'] == 'a-new'
    state.accept([event('a-new', 1, 21)])
    assert len(state.snapshot()['entries']) == 2
    state.accept([event('z-old', 0, 30)])  # genuinely re-sliced old project becomes current
    assert state.snapshot()['project'] == 'z-old'
    assert len(state.snapshot()['entries']) == 3
    restart = ForecastState()
    restart.accept(list(reversed(list(state.entries.values()))))
    assert restart.snapshot()['project'] == 'z-old'


def test_reserve_changes_label_value_and_decision_without_slice(tmp_path):
    from storage import Store
    store = Store(tmp_path / 'data', legacy_paths=())
    def seed(db):
        db['spools'] = {'a': {'name':'A', 'material':'PLA', 'remaining_g':10}}
        db['slots']['1'] = 'a'
        db['safety_margin_g'] = 0
    store.update(seed)
    state = ForecastState(store=store); state.accept([entry(0, 8)])
    assert not state.snapshot()['entries'][0]['shortage']
    for reserve in (2.5, 0):
        store.update(lambda db: db.update(safety_margin_g=reserve))
        s = state.snapshot()
        assert s['safety_margin_g'] == reserve
        assert s['entries'][0]['shortage'] == (reserve > 2)
        assert s['revision'] == 1
