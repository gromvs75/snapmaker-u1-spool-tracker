"""Physical instance ID pairing, collision guards and persistent balances."""
import copy
import sqlite3
import pytest
from test_rfid_bambu import env, tag as bambu, Fleet, Server
from test_rfid_all_formats import tag as other_tag, settings
from tracker_uid import decode_openprinttag, decode_opentag, ndef_records
from tracker_rfid_metadata import validate_tag, roll_key
from tracker_rfid import RfidWorker
from tracker_uid_runtime import AccountingOwner
from tracker_uid_catalog import UidCatalog
from tracker_uid_accounting import UidAccounting
from tracker_uid_library import Library
from dev.labs.uid_live_bench.roll_identity_fixtures import INSTANCE, payload
from dev.labs.uid_live_bench.all_tag_fixtures import fixture


def tag(uid='04052233445501', instance=INSTANCE, **fields):
    result = decode_openprinttag(bytes.fromhex(uid), payload(instance, **fields))
    assert validate_tag(result, uid) == result
    return result


def setup(env, *tags):
    o, f, s, w, path = env
    f.set(tags[0])
    o.call('save_settings', {'rfid': settings(list(tags))}, o.call('settings')['revision'])
    return o, f, s, w, path


@pytest.mark.parametrize('value', [b'', bytes(15), bytes(17), bytes(16), b'\xff'*16, '1234', 12])
def test_invalid_explicit_instance_fails_closed(value):
    with pytest.raises(ValueError, match='instance UUID'):
        decode_openprinttag(bytes.fromhex('04052233445501'), payload(value))


def test_instance_is_distinct_from_product_and_chip():
    a, b = tag(), tag('04052233445502')
    assert a['identity'] != b['identity'] and roll_key(a) == roll_key(b)
    # Product UUID, GTIN and brand-specific PRODUCT ID never identify a roll.
    c = tag(instance=None, **{'1': INSTANCE, '4': 12345, '6': 'PRODUCT'})
    assert roll_key(c) is None
    for v in ('0'*32, 'F'*32, 'bad', INSTANCE.hex(), 2, None):
        with pytest.raises(ValueError): validate_tag(dict(a, instance_uuid=v), a['uid'])


def test_second_uid_auto_pairs_in_interactive_mode_without_reset(env):
    a, b = tag(), tag('04052233445502')
    o, f, s, w, path = setup(env, a)
    first = w.scan('a', '0');s.rows['spool'][0]['remaining_weight'] = 712.345
    w.interactive = True;f.set(b)
    second = w.scan('a', '0')
    assert (second['spool_id'], second['remaining_mg']) == (first['spool_id'], 712345)
    assert s.posts.count('spool') == 1
    saved = o.call('backup_package')
    checked = o.call('validate_backup', package=saved)
    o.call('restore_backup', package=saved, expected_revision=checked['current_revision'])
    assert not o.call('settings')['values'].get('rfid', {}).get('enabled')
    o.call('save_settings', {'spoolman_url': 'http://127.0.0.1:1', 'spoolman_mode': 'send', 'rfid': settings([a])}, o.call('settings')['revision'])
    o.close();new = AccountingOwner(path, f)
    try:
        worker = RfidWorker(new, w.allowed_urls, client_factory=s, interactive=True)
        # A third previously unseen UID proves shared-key restoration, not just aliases.
        for t in (a, b, tag('04052233445503')):
            f.set(t);got = worker.scan('a', '0')
            assert (got['spool_id'], got['remaining_mg']) == (first['spool_id'], 712345)
        assert len(s.rows['spool']) == 1
    finally: new.close()


def test_identical_product_distinct_instance_stays_separate(env):
    a, b = tag(), tag('04052233445502', bytes.fromhex('12346F54D4754C33A89C15C14AFA9D11'))
    o, f, s, w, _ = setup(env, a, b)
    first = w.scan('a', '0');s.rows['spool'][0]['remaining_weight'] = 700
    f.set(b);ticket = o.call('rfid_prepare', 'a', '0')
    assert o.call('rfid_candidates', ticket) == []
    with pytest.raises(ValueError, match='Physical roll ID'):
        o.call('rfid_pair', ticket, first['spool_id'], confirmed=True)
    second = w.scan('a', '0')
    assert second['spool_id'] != first['spool_id'] and len(s.rows['spool']) == 2


@pytest.mark.parametrize('fault', ['two_heads', 'metadata', 'changed_instance', 'already_bound', 'creation_attempt'])
def test_ambiguous_or_conflicting_shared_id_does_not_write(env, fault):
    a, b = tag(), tag('04052233445502')
    o, f, s, w, path = setup(env, a)
    w.scan('a', '0')
    if fault == 'two_heads': f.set(a, '1')
    elif fault == 'metadata': b['color'] = 'FFFFFF';b['colors'] = ['FFFFFF']
    elif fault == 'changed_instance': b = tag(a['uid'], bytes.fromhex('12346F54D4754C33A89C15C14AFA9D11'))
    elif fault == 'already_bound': o.call('register', b['uid'], 'Another physical spool', 800000)
    else:
        # A previous uncertain remote create must not be silently abandoned.
        with sqlite3.connect(path) as db:
            db.execute('INSERT INTO uid_rfid_creations VALUES(?,?,?)',
                       ('http://127.0.0.1:1', 'Tracker RFID '+b['identity'], 1))
    f.set(b);before = copy.deepcopy(s.rows)
    with pytest.raises(ValueError): w.scan('a', '0')
    assert s.rows == before and s.posts.count('spool') == 1


def test_pending_local_debit_survives_new_uid(env):
    a, b = tag(), tag('04052233445502')
    o, f, s, w, path = setup(env, a);first = w.scan('a', '0');o.close()
    c = UidCatalog(path);accounting = UidAccounting(c);Library(accounting)
    job = accounting.begin('a', 'print', '1', ['0'], 'fixture', f.snapshot())
    accounting.apply(job, 1, {'0': 12500}, state='completed', source='fixture', basis='executed_gcode')
    c.close();new = AccountingOwner(path, f)
    try:
        f.set(b);got = RfidWorker(new, w.allowed_urls, client_factory=s).scan('a', '0')
        assert (got['spool_id'], got['remaining_mg'], got['balance_source']) == (first['spool_id'], 987500, 'local')
        assert s.rows['spool'][0]['remaining_weight'] == 1000
    finally: new.close()


def test_old_chip_registration_acquires_key_without_changing_remote_marker(env):
    old = tag(instance=None)
    o, f, s, w, _ = setup(env, old);first = w.scan('a', '0')
    marker = s.rows['spool'][0]['comment']
    f.set(tag());assert w.scan('a', '0')['spool_id'] == first['spool_id']
    f.set(tag('04052233445502'));assert w.scan('a', '0')['spool_id'] == first['spool_id']
    assert len(s.rows['spool']) == 1 and s.rows['spool'][0]['comment'] == marker


@pytest.mark.parametrize('kind', ['creality', 'elegoo', 'tigertag', 'generic-ndef', 'opentag', 'openprinttag'])
def test_weak_or_missing_ids_never_auto_merge(env, kind):
    a, b = other_tag(kind), other_tag(kind, 1)
    o, f, s, w, _ = setup(env, a);w.scan('a', '0');w.interactive = True
    f.set(b)
    with pytest.raises(ValueError, match='Подтвердите'): w.scan('a', '0')
    assert len(s.rows['spool']) == 1 and roll_key(a) is None and roll_key(b) is None


def test_opentag_batch_serial_is_not_a_roll_id():
    raw = bytearray(ndef_records(fixture('opentag'))[0][1])
    raw[76:84] = b'BATCH-42'
    for uid in ('04042233445501', '04042233445502'):
        assert roll_key(decode_opentag(bytes.fromhex(uid), raw)) is None


@pytest.mark.parametrize('failure', ['before_spool', 'after_spool'])
def test_lost_creation_reply_uses_same_marker_across_both_chips(env, failure):
    a, b = tag(), tag('04052233445502')
    o, f, s, w, _ = setup(env, a, b)
    s.fail = failure
    with pytest.raises(OSError): w.scan('a', '0')
    s.fail = None;f.set(b)
    if failure == 'after_spool':
        got = w.scan('a', '0')
        assert got['remaining_mg'] == 1000000 and len(s.rows['spool']) == 1
        assert s.rows['spool'][0]['comment'] == 'Tracker RFID '+roll_key(a)
    else:
        with pytest.raises(ValueError, match='Previous POST outcome unknown'): w.scan('a', '0')
        assert not s.rows['spool']
    assert s.posts.count('spool') == 1


def test_older_backup_without_roll_key_table_is_migrated(env, tmp_path):
    from tracker_uid_backup import export
    o, f, s, w, path = setup(env, tag());w.scan('a', '0')
    # An older schema has no common-ID index; import must add it only in the copy.
    with sqlite3.connect(path) as source, sqlite3.connect(tmp_path/'old.sqlite') as old:
        source.backup(old)
        old.execute('DROP TABLE uid_rfid_roll_keys');old.commit()
        saved = export(old)
    preview = o.call('validate_backup', package=saved)
    assert preview['migrated_tables'] == ['uid_rfid_roll_keys']
    with sqlite3.connect(path) as source:
        assert source.execute('SELECT count(*) FROM uid_rfid_roll_keys').fetchone()[0] == 1
