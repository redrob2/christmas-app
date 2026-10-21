"""One-file backups: everything (database + photos) in a passphrase-protected file.

Admin -> Settings -> "Backup & move" downloads one; a new install's first-run page
(or Settings, to replace everything) restores it. The same file works between
versions: older backups are upgraded on restore, like the copy-database command.

File layout (".xmasbackup"):
    MAGIC (8 bytes) | salt (16) | nonce prefix (8) | chunks...
    chunk = length (4 bytes, big-endian) | AES-256-GCM ciphertext+tag
Each chunk's nonce is prefix + chunk number, and the chunk number plus a
"last chunk" flag are authenticated, so a cut-off or reordered file is rejected.
Inside is a zip: manifest.json, tables/<name>.json, uploads/<photos>.
The key comes from the passphrase via scrypt; a wrong one simply fails to decrypt.
"""
import json
import os
import shutil
import struct
import tempfile
import zipfile
from datetime import date, datetime
from decimal import Decimal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from flask import current_app
from sqlalchemy import func, select, text

from app import db

MAGIC = b'XMASBK1\n'
FORMAT = 1
CHUNK = 1024 * 1024
SKIP_TABLES = {'login_failures'}      # short-lived, not worth moving
EXTENSION = '.xmasbackup'


class BackupError(Exception):
    """Shown to the admin as-is"""


# ---------- encryption ----------

def _key(passphrase, salt):
    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode('utf-8'))


def _encrypt_file(src_path, dst_path, passphrase):
    salt, prefix = os.urandom(16), os.urandom(8)
    aead = AESGCM(_key(passphrase, salt))
    size = os.path.getsize(src_path)
    with open(src_path, 'rb') as src, open(dst_path, 'wb') as dst:
        dst.write(MAGIC + salt + prefix)
        index, done = 0, 0
        while True:
            block = src.read(CHUNK)
            done += len(block)
            last = done >= size
            nonce = prefix + struct.pack('>I', index)
            sealed = aead.encrypt(nonce, block, struct.pack('>I?', index, last))
            dst.write(struct.pack('>I', len(sealed)) + sealed)
            index += 1
            if last:
                break


def _decrypt_file(src_path, dst_path, passphrase):
    with open(src_path, 'rb') as src, open(dst_path, 'wb') as dst:
        if src.read(len(MAGIC)) != MAGIC:
            raise BackupError("That isn't a backup file from this app.")
        salt, prefix = src.read(16), src.read(8)
        aead = AESGCM(_key(passphrase, salt))
        index, finished = 0, False
        while True:
            header = src.read(4)
            if not header:
                break
            if finished:
                raise BackupError('The backup file has extra data at the end - it may be damaged.')
            length = struct.unpack('>I', header)[0]
            sealed = src.read(length)
            if len(sealed) != length or length > CHUNK + 64:
                raise BackupError('The backup file is incomplete - it may not have downloaded fully.')
            nonce = prefix + struct.pack('>I', index)
            for last in (False, True):
                try:
                    dst.write(aead.decrypt(nonce, sealed, struct.pack('>I?', index, last)))
                    finished = last
                    break
                except InvalidTag:
                    continue
            else:
                if index == 0:
                    raise BackupError("Wrong passphrase (or the file is damaged).")
                raise BackupError('The backup file is damaged.')
            index += 1
        if not finished:
            raise BackupError('The backup file is incomplete - it may not have downloaded fully.')


# ---------- export ----------

def _jsonable(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f'cannot store {type(value).__name__}')


def export_backup(passphrase, app_version=''):
    """Writes an encrypted backup to a temporary file and returns (path, summary)."""
    from app import models  # noqa: F401  (register every table)
    if len(passphrase or '') < 8:
        raise BackupError('Choose a passphrase of at least 8 characters.')
    work = tempfile.mkdtemp(prefix='xmas-export-')
    inner = os.path.join(work, 'inner.zip')
    counts = {}
    try:
        with zipfile.ZipFile(inner, 'w', zipfile.ZIP_DEFLATED) as zf:
            for table in db.metadata.sorted_tables:
                if table.name in SKIP_TABLES:
                    continue
                rows = [dict(r._mapping) for r in db.session.execute(select(table)).all()]
                counts[table.name] = len(rows)
                zf.writestr(f'tables/{table.name}.json', json.dumps(rows, default=_jsonable, ensure_ascii=False))
            uploads = current_app.config.get('UPLOAD_FOLDER')
            photos = 0
            if uploads and os.path.isdir(uploads):
                for root, _, files in os.walk(uploads):
                    for name in files:
                        path = os.path.join(root, name)
                        arc = 'uploads/' + os.path.relpath(path, uploads).replace(os.sep, '/')
                        # photos are already compressed
                        zf.write(path, arc, compress_type=zipfile.ZIP_STORED)
                        photos += 1
            manifest = {
                'format': FORMAT,
                'created': datetime.utcnow().isoformat() + 'Z',
                'app_version': app_version,
                'database': db.engine.dialect.name,
                'tables': counts,
                'photos': photos,
                # so people stay signed in after a move (only used if the new install
                # doesn't set SECRET_KEY itself)
                'secret_key': current_app.config.get('SECRET_KEY'),
            }
            zf.writestr('manifest.json', json.dumps(manifest, indent=1))
        out = os.path.join(work, 'backup' + EXTENSION)
        _encrypt_file(inner, out, passphrase)
        os.remove(inner)
        return out, {'tables': counts, 'photos': photos}
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise


# ---------- import ----------

def _convert(column, value):
    if value is None:
        return None
    kind = type(column.type).__name__
    if kind == 'DateTime':
        return datetime.fromisoformat(value.rstrip('Z')) if isinstance(value, str) else value
    if kind == 'Date':
        return date.fromisoformat(value) if isinstance(value, str) else value
    if kind == 'Numeric':
        return Decimal(str(value))
    if kind == 'Boolean':
        return bool(value)
    return value


def read_backup(path, passphrase):
    """Decrypts and opens a backup. Returns (work_dir, zipfile, manifest)."""
    work = tempfile.mkdtemp(prefix='xmas-import-')
    inner = os.path.join(work, 'inner.zip')
    try:
        _decrypt_file(path, inner, passphrase)
        zf = zipfile.ZipFile(inner)
        manifest = json.loads(zf.read('manifest.json'))
        if manifest.get('format') != FORMAT:
            raise BackupError('This backup was made by a newer version of the app - update this one first.')
        return work, zf, manifest
    except (zipfile.BadZipFile, KeyError, ValueError):
        shutil.rmtree(work, ignore_errors=True)
        raise BackupError('The backup file is damaged.')
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise


def restore_backup(path, passphrase):
    """Replaces ALL data (database and photos) with the backup's. Returns a summary.
    The database part is one transaction: if anything fails, nothing changes."""
    from app import add_missing_columns, models  # noqa: F401
    work, zf, manifest = read_backup(path, passphrase)
    try:
        names = set(zf.namelist())
        tables = [t for t in db.metadata.sorted_tables if t.name not in SKIP_TABLES]
        # Never restore a backup nobody could sign in to (checked before anything changes)
        users = json.loads(zf.read('tables/users.json')) if 'tables/users.json' in names else []
        if not any(u.get('is_admin') and not u.get('is_managed') and u.get('is_approved', True) for u in users):
            raise BackupError('This backup has no admin account, so nobody could sign in after restoring it.')
        db.session.remove()
        engine = db.engine
        restored = {}
        with engine.begin() as conn:
            for table in reversed(db.metadata.sorted_tables):
                conn.execute(table.delete())
            for table in tables:
                member = f'tables/{table.name}.json'
                rows = json.loads(zf.read(member)) if member in names else []
                columns = {c.name: c for c in table.columns}
                pk = table.primary_key.columns.values()[0] if table.primary_key else None
                self_refs = [fk.parent.name for fk in table.foreign_keys if fk.column.table is table]
                links, batch = [], []
                for row in rows:
                    data = {k: _convert(columns[k], v) for k, v in row.items() if k in columns}
                    for col in self_refs:
                        if data.get(col) is not None:
                            links.append((data[pk.name], col, data[col]))
                            data[col] = None
                    batch.append(data)
                for i in range(0, len(batch), 500):
                    conn.execute(table.insert(), batch[i:i + 500])
                for row_id, col, value in links:
                    conn.execute(table.update().where(pk == row_id).values({col: value}))
                got = conn.execute(select(func.count()).select_from(table)).scalar()
                if got != len(rows):
                    raise BackupError(f'{table.name}: the backup has {len(rows)} rows but {got} were restored.')
                restored[table.name] = got
            if engine.dialect.name == 'postgresql':
                for table in tables:
                    pk = table.primary_key.columns.values()[0] if table.primary_key else None
                    if pk is not None and isinstance(pk.type, db.Integer):
                        conn.execute(text(
                            f"SELECT setval(pg_get_serial_sequence('{table.name}', '{pk.name}'), "
                            f"COALESCE((SELECT MAX({pk.name}) FROM \"{table.name}\"), 1))"))
        add_missing_columns()

        # Photos: replace the uploads folder with the backup's (never writing outside it)
        uploads = current_app.config.get('UPLOAD_FOLDER')
        photos = 0
        if uploads:
            base = os.path.realpath(uploads)
            staging = os.path.join(work, 'uploads')
            for name in names:
                if not name.startswith('uploads/') or name.endswith('/'):
                    continue
                target = os.path.realpath(os.path.join(staging, name[len('uploads/'):]))
                if not target.startswith(os.path.realpath(staging) + os.sep):
                    continue   # "../" tricks in a crafted file
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(name) as src, open(target, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
                photos += 1
            os.makedirs(base, exist_ok=True)
            for entry in os.listdir(base):
                path = os.path.join(base, entry)
                shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
            if os.path.isdir(staging):
                for entry in os.listdir(staging):
                    shutil.move(os.path.join(staging, entry), os.path.join(base, entry))
            for sub in ('profiles', 'items'):
                os.makedirs(os.path.join(base, sub), exist_ok=True)

        # Keep everyone signed in: adopt the old secret key (takes effect on restart)
        secret_written = False
        data_path = current_app.config.get('DATA_PATH')
        if manifest.get('secret_key') and data_path and not os.environ.get('SECRET_KEY'):
            with open(os.path.join(data_path, 'secret_key'), 'w') as f:
                f.write(manifest['secret_key'])
            secret_written = True

        from app.models import AppSettings, User
        settings = AppSettings.query.first()
        if settings is None:   # (very old backups)
            settings = AppSettings(site_name='Family Christmas')
            db.session.add(settings)
            db.session.commit()
        if settings.setup_code and User.query.filter_by(is_admin=True).first():
            settings.setup_code = None
            db.session.commit()
        from app.push import ensure_vapid_keys
        ensure_vapid_keys()
        return {'tables': restored, 'photos': photos, 'secret_key': secret_written,
                'created': manifest.get('created'), 'people': restored.get('users', 0),
                'events': restored.get('christmas_events', 0)}
    finally:
        zf.close()
        shutil.rmtree(work, ignore_errors=True)


def restart_workers_soon(request):
    """After a restore, restart the web workers so they all load the restored secret key
    and notification keys (gunicorn reloads its workers on SIGHUP). No-op elsewhere."""
    if not request.environ.get('SERVER_SOFTWARE', '').startswith('gunicorn'):
        return None
    import signal

    def restart():
        try:
            os.kill(os.getppid(), signal.SIGHUP)
        except OSError:
            pass
    return restart
