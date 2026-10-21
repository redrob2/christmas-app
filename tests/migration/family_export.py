"""Exports a backup from a filled database using the given repo's code (e.g. the older
family edition), via its Admin -> Settings "Download backup" button.
usage: python family_export.py <repo> <database-url> <uploads-dir> <out-file> <passphrase>"""
import os, re, sys

repo, url, uploads, out, passphrase = sys.argv[1:6]
os.environ.update(DATABASE_URL=url, SECRET_KEY='family-secret', PREFERRED_URL_SCHEME='http',
                  UPLOAD_FOLDER=uploads, DATA_PATH=os.path.dirname(uploads))
sys.path.insert(0, repo)
from app import create_app, db
app = create_app('production')
app.config['TESTING'] = True
from app.models import User

c = app.test_client()
t = re.search(r'name="csrf-token" content="([^"]+)"', c.get('/login').get_data(as_text=True)).group(1)
assert c.post('/login', data={'email': 'rob@family.test', 'password': 'robpass123', 'csrf_token': t}).status_code == 302
with c.session_transaction() as s:
    s['event_choice_asked'] = True
page = c.get('/admin/settings').get_data(as_text=True)
assert 'Download backup' in page
t = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
r = c.post('/admin/backup/export', data={'passphrase': passphrase, 'confirm_passphrase': passphrase, 'csrf_token': t})
assert r.status_code == 200 and 'attachment' in r.headers['Content-Disposition'], (r.status_code, r.get_data()[:300])
assert '.xmasbackup' in r.headers['Content-Disposition']
with open(out, 'wb') as f:
    f.write(r.get_data())
r.close()
print('EXPORTED', os.path.getsize(out))
