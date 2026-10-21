"""Backup & move: family-style database exported with the Download backup button (by the
given repo's code), restored on a fresh install's first-run page, then round trips,
damaged files, wrong passphrases and safety checks.
usage: python backup_test.py <repo> <repo-that-exports> [source-database-url]"""
import ast, io, os, re, struct, subprocess, sys, tempfile, zipfile
from decimal import Decimal

repo, export_repo = sys.argv[1], sys.argv[2]
here = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp()
source_url = sys.argv[3] if len(sys.argv) > 3 else f'sqlite:///{tmp}/family.db'
PASS = 'snowy owl 2026'

# 1. a filled family database + photos (one bigger than the normal 16 MB upload limit)
seed = subprocess.run([sys.executable, '-W', 'ignore', os.path.join(here, 'seed_family.py'), export_repo, source_url],
                      capture_output=True, text=True)
assert seed.returncode == 0, seed.stderr[-2000:]
vapid = re.search(r'^VAPID (\S+)', seed.stdout, re.M).group(1)
counts = ast.literal_eval(re.search(r'^COUNTS (.*)$', seed.stdout, re.M).group(1))
old_uploads = os.path.join(tmp, 'olddata', 'uploads')
os.makedirs(os.path.join(old_uploads, 'items'))
os.makedirs(os.path.join(old_uploads, 'profiles'))
open(os.path.join(old_uploads, 'items', 'a.jpg'), 'wb').write(b'\xff\xd8photo-a')
big = os.urandom(20 * 1024 * 1024)
open(os.path.join(old_uploads, 'profiles', 'big.png'), 'wb').write(big)

# 2. export with the exporting repo's own button
backup = os.path.join(tmp, 'family.xmasbackup')
exp = subprocess.run([sys.executable, '-W', 'ignore', os.path.join(here, 'family_export.py'), export_repo, source_url,
                      old_uploads, backup, PASS], capture_output=True, text=True)
assert exp.returncode == 0, exp.stdout[-1500:] + exp.stderr[-2500:]
raw = open(backup, 'rb').read()
assert raw.startswith(b'XMASBK1\n') and b'rob@family.test' not in raw and b'photo-a' not in raw, 'must be encrypted'
print('exported', len(raw) // 1024, 'KB')

# 3. a fresh single-container install
data = os.path.join(tmp, 'appdata')
for k in ('DATABASE_URL', 'SECRET_KEY', 'UPLOAD_FOLDER', 'ASSIGNMENTS_FILE_PATH'):
    os.environ.pop(k, None)
os.environ.update(DATA_PATH=data, PREFERRED_URL_SCHEME='http')
if os.environ.get('TARGET_DATABASE_URL'):
    os.environ['DATABASE_URL'] = os.environ['TARGET_DATABASE_URL']
sys.path.insert(0, repo)
from app import create_app, db
app = create_app('production')
app.config['TESTING'] = True
app.extensions['mail'].suppress = True
from app.models import *
with app.app_context():
    code = AppSettings.query.first().setup_code


def csrf(c, path):
    return re.search(r'name="csrf-token" content="([^"]+)"', c.get(path).get_data(as_text=True)).group(1)


def flashes(c):
    with c.session_transaction() as s:
        return ' '.join(m for _, m in s.pop('_flashes', []))


def restore_on_setup(c, file_bytes, passphrase=PASS, setup_code=None):
    return c.post('/setup/restore', data={'csrf_token': csrf(c, '/setup'), 'setup_code': setup_code or code,
                                          'passphrase': passphrase,
                                          'backup_file': (io.BytesIO(file_bytes), 'family.xmasbackup')},
                  content_type='multipart/form-data')


c = app.test_client()
assert 'Moving from another install?' in c.get('/setup').get_data(as_text=True)
# wrong code / wrong passphrase / damaged or cut-off / not a backup: nothing changes
for kwargs, data_bytes, expect in [({'setup_code': 'AAAA-BBBB-CCCC'}, raw, "setup code isn"),
                                   ({'passphrase': 'wrong passphrase'}, raw, 'Wrong passphrase'),
                                   ({}, raw[:-5000], 'incomplete'),
                                   ({}, raw[:len(raw) // 2] + bytes([raw[len(raw) // 2] ^ 1]) + raw[len(raw) // 2 + 1:], 'damaged'),
                                   ({}, b'PK\x03\x04 not ours', "isn't a backup file")]:
    r = restore_on_setup(c, data_bytes, **kwargs)
    assert r.status_code == 302 and '/setup' in r.headers['Location'], r.status_code
    msg = flashes(c)
    assert expect in msg.replace('&#39;', "'"), (expect, msg)
    with app.app_context():
        assert User.query.count() == 0
print('bad files rejected')

r = restore_on_setup(c, raw)
assert r.status_code == 302 and r.headers['Location'].endswith('/login'), (r.status_code, r.headers.get('Location'), flashes(c))
assert 'Restored 6 people, 1 events and 2 photos' in flashes(c)

with app.app_context():
    for table, n in counts.items():
        if table == 'login_failures':
            continue
        got = db.session.execute(db.select(db.func.count()).select_from(db.metadata.tables[table])).scalar()
        expected = n + (1 if table == 'activity_log' else 0)   # + "backup restored"
        assert got == expected, (table, expected, got)
    rob = User.query.filter_by(email='rob@family.test').one()
    assert rob.is_admin and rob.check_password('robpass123')
    assert User.query.filter_by(name='Maya').one().managed_by.name == 'Elizabeth'
    items = {i.name: i for i in WishListItem.query.all()}
    assert items['Stand mixer'].price == Decimal('399.99') and items['Wool socks'].purchase.status == 'wrapped'
    st = AppSettings.query.first()
    assert st.vapid_private_key == vapid and st.setup_code is None and st.site_name == 'The James Family'
    assert ChristmasEvent.query.one().lists_lock_date.day == 15
    assert SantaMessage.query.one().body.endswith('🎄')
uploads = os.path.join(data, 'uploads')
assert open(os.path.join(uploads, 'items', 'a.jpg'), 'rb').read() == b'\xff\xd8photo-a'
assert open(os.path.join(uploads, 'profiles', 'big.png'), 'rb').read() == big
assert open(os.path.join(data, 'secret_key')).read() == 'family-secret', 'everyone stays signed in after restart'
assert c.get('/setup').status_code == 302
r = c.post('/login', data={'email': 'ann@family.test', 'password': 'annpass123', 'csrf_token': csrf(c, '/login')})
assert r.status_code == 302 and '/setup' not in r.headers['Location']
print('family backup restored on first run')

# 4. normal uploads keep their 16 MB limit
r = c.post('/profile/upload-photo', data={'csrf_token': csrf(c, '/profile/'),
                                           'photo': (io.BytesIO(big), 'big.png')}, content_type='multipart/form-data')
assert r.status_code in (302, 413), r.status_code
assert r.status_code == 413 or 'too large' in flashes(c)

# 5. Settings: export from the new install, change things, restore it back
a = app.test_client()
assert a.post('/login', data={'email': 'rob@family.test', 'password': 'robpass123', 'csrf_token': csrf(a, '/login')}).status_code == 302
with a.session_transaction() as s:
    s['event_choice_asked'] = True
settings_html = a.get('/admin/settings').get_data(as_text=True)
assert 'Download backup' in settings_html and 'Replace everything with this backup' in settings_html
r = a.post('/admin/backup/export', data={'csrf_token': csrf(a, '/admin/settings'), 'passphrase': 'short', 'confirm_passphrase': 'short'})
assert r.status_code == 302 and 'at least 8' in flashes(a)
r = a.post('/admin/backup/export', data={'csrf_token': csrf(a, '/admin/settings'), 'passphrase': PASS, 'confirm_passphrase': 'other one'})
assert "don't match" in flashes(a).replace('&#39;', "'")
r = a.post('/admin/backup/export', data={'csrf_token': csrf(a, '/admin/settings'), 'passphrase': PASS, 'confirm_passphrase': PASS})
assert r.status_code == 200
second = r.get_data(); r.close()
ann = app.test_client()
ann.post('/login', data={'email': 'ann@family.test', 'password': 'annpass123', 'csrf_token': csrf(ann, '/login')})
assert ann.post('/admin/backup/export', data={'csrf_token': csrf(ann, '/profile/'), 'passphrase': PASS,
                                               'confirm_passphrase': PASS}).status_code == 302, 'admins only'
with app.app_context():
    u = User(email='later@x.com', name='Later'); u.set_password('laterpass1'); db.session.add(u)
    WishListItem.query.filter_by(name='Wool socks').one().name = 'Changed after backup'
    db.session.commit()
os.remove(os.path.join(uploads, 'items', 'a.jpg'))


def settings_restore(client, **kw):
    form = {'csrf_token': csrf(client, '/admin/settings'), 'passphrase': PASS, 'password': 'robpass123', 'confirm': 'RESTORE',
            'backup_file': (io.BytesIO(second), 'b.xmasbackup')}
    form.update(kw)
    return client.post('/admin/backup/restore', data=form, content_type='multipart/form-data')


r = settings_restore(a, password='wrong')
assert 'password is not right' in flashes(a)
r = settings_restore(a, confirm='yes')
assert 'Type RESTORE' in flashes(a)
with app.app_context():
    assert User.query.filter_by(email='later@x.com').count() == 1
r = settings_restore(a)
assert r.status_code == 302 and r.headers['Location'].endswith('/login'), flashes(a)
with app.app_context():
    assert User.query.filter_by(email='later@x.com').count() == 0
    assert WishListItem.query.filter_by(name='Wool socks').count() == 1
assert os.path.exists(os.path.join(uploads, 'items', 'a.jpg'))
assert a.get('/admin/').status_code == 302, 'signed out after a restore'
print('settings export / restore round trip ok')

# 6. a crafted backup can't write outside the uploads folder
sys.path.insert(0, repo)
from app import backup as bk
inner = io.BytesIO()
def craft(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('manifest.json', '{"format": 1}')
        for name, body in files.items():
            zf.writestr(name, body)
    plain = os.path.join(tmp, 'crafted.zip'); open(plain, 'wb').write(buf.getvalue())
    path = os.path.join(tmp, 'crafted.xmasbackup')
    bk._encrypt_file(plain, path, PASS)
    return path


# no admin in it: refused before anything changes
with app.app_context():
    before = User.query.count()
try:
    with app.test_request_context():
        bk.restore_backup(craft({'tables/users.json': '[]'}), PASS)
    raise AssertionError('should refuse')
except bk.BackupError as e:
    assert 'no admin' in str(e)
with app.app_context():
    assert User.query.count() == before
admin_row = '[{"id": 1, "email": "x@x.com", "name": "X", "password_hash": "x", "is_admin": true}]'
crafted = craft({'tables/users.json': admin_row, 'uploads/../../evil.txt': 'nope', 'uploads/items/ok.jpg': 'fine'})
with app.test_request_context():
    bk.restore_backup(crafted, PASS)
with app.app_context():
    assert AppSettings.query.count() == 1, 'settings recreated'
assert not os.path.exists(os.path.join(data, 'evil.txt')) and not os.path.exists(os.path.join(tmp, 'evil.txt'))
assert os.path.exists(os.path.join(uploads, 'items', 'ok.jpg'))
print('ALL OK')
