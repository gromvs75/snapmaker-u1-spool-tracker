"""Versioned SQLite backup envelopes; validation never opens live/user paths."""
import base64
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

MAX_BACKUP = 32 * 1024 * 1024

# Additive 2.0 development schemas, never a generic "accept any missing table".
RECOVERY_ADDITIONS = {'uid_recovery_profiles', 'uid_recovery_receipts',
                     'uid_replacement_state', 'uid_replacement_events',
                     'uid_recovery_decisions'}


def migrate_copy(db, live):
    """Upgrade a disposable, checksum-verified copy using trusted local DDL."""
    expected = {r[1]: r for r in schema(live)}
    actual = {r[1]: r for r in schema(db)}
    missing = set(expected)-set(actual)
    if (set(actual)-set(expected) or missing-RECOVERY_ADDITIONS
            or any(actual[name] != expected[name] for name in actual)):
        raise ValueError('Схема копии отличается от поддерживаемых версий Tracker.')
    with db:
        for name in sorted(missing):
            db.execute(expected[name][3])
    return sorted(missing)


def schema(db):
    return [tuple(r) for r in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")]


def fingerprint(db):
    # Covers preferences, ledger, queues and decisions, including concurrent writes.
    return hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest()


def export(db):
    with tempfile.TemporaryDirectory(prefix='uid-export-') as folder:
        path = Path(folder)/'copy.sqlite'
        copy = sqlite3.connect(path)
        try:
            db.backup(copy)
            if copy.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or copy.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Проверка целостности копии не пройдена.')
        finally:
            copy.close()
        raw = path.read_bytes()
    return {'format':'tracker-uid-backup','version':1,'sha256':hashlib.sha256(raw).hexdigest(),
            'base64':base64.b64encode(raw).decode()}


def decode(package):
    if not isinstance(package,dict) or set(package)!={'format','version','sha256','base64'} or package['format']!='tracker-uid-backup' or type(package['version']) is not int or package['version']!=1:
        raise ValueError('Неподдерживаемый формат резервной копии.')
    if not isinstance(package['base64'],str) or len(package['base64'])>MAX_BACKUP*4//3+4:
        raise ValueError('Резервная копия слишком велика.')
    try: raw=base64.b64decode(package['base64'],validate=True)
    except Exception as exc: raise ValueError('Неверное содержимое копии.') from exc
    if hashlib.sha256(raw).hexdigest()!=package['sha256']:
        raise ValueError('Контрольная сумма копии не совпадает.')
    return raw


def validate(package, live):
    raw=decode(package)
    with tempfile.TemporaryDirectory(prefix='uid-validate-') as folder:
        path=Path(folder)/'copy.sqlite';path.write_bytes(raw)
        db=sqlite3.connect(path)
        try:
            db.execute('PRAGMA trusted_schema=OFF')
            migrated=migrate_copy(db,live)
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Нарушена целостность SQLite или связей.')
            if schema(db)!=schema(live):raise ValueError('Схема копии отличается от этой версии Tracker.')
            result={name:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for name,table in
                    [('spools','uid_spools'),('jobs','uid_jobs'),('debits','uid_debits'),('remote_operations','uid_remote_outbox')]}
            # SQLite integrity does not validate application JSON.
            for payload, in db.execute('SELECT payload FROM uid_preferences'):json.loads(payload)
            from tracker_uid_settings import validate_printers
            row=db.execute("SELECT payload FROM uid_preferences WHERE key='printers'").fetchone()
            if row:validate_printers(json.loads(row[0]))
            result.update(sha256=package['sha256'],current_revision=fingerprint(live),migrated_tables=migrated)
            return result
        except (sqlite3.Error,TypeError,json.JSONDecodeError) as exc:
            raise ValueError('Резервная копия повреждена.') from exc
        finally:db.close()


def restore(package, live, expected_revision):
    preview=validate(package,live)
    if preview['current_revision']!=expected_revision:
        raise ValueError('Текущая база изменилась после проверки. Проверьте копию снова.')
    raw=decode(package)
    with tempfile.TemporaryDirectory(prefix='uid-restore-') as folder:
        path=Path(folder)/'copy.sqlite';path.write_bytes(raw)
        source=sqlite3.connect(path)
        try:
            source.execute('PRAGMA trusted_schema=OFF')
            migrate_copy(source,live)
            with source:
                source.execute('UPDATE manual_assignments SET confirmed=0,version=lower(hex(randomblob(16)))')
                source.execute('UPDATE uid_locations SET confirmed=0')
                source.execute("UPDATE uid_jobs SET mapping_valid=0 WHERE state='active'")
                if source.execute("SELECT 1 FROM sqlite_master WHERE name='uid_recovery_profiles'").fetchone():
                    source.execute('UPDATE uid_recovery_profiles SET quarantined=1')
                source.execute('DELETE FROM uid_unlock_windows')
                source.execute('DELETE FROM uid_unlock_attempts')
                source.execute("UPDATE uid_remote_outbox SET state='uncertain' WHERE state IN ('held','pending','sending')")
                source.execute('UPDATE uid_delivery_meta SET revision=lower(hex(randomblob(16))),attempt=NULL')
            source.backup(live)
        finally:source.close()
    return preview
