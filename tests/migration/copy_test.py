"""Tests copy-database: builds a filled "old" database (seed_family.py), copies it into a
fresh install and checks every row, password, link and setting came across.
usage: python copy_test.py <repo> <repo-that-builds-the-source> [source-url]
SOURCE defaults to a SQLite file; TARGET_DATABASE_URL picks the target (default: SQLite).
The source database must be empty."""
import ast, os, re, subprocess, sys, tempfile
from decimal import Decimal

ca_repo, family_repo = sys.argv[1], sys.argv[2]
here = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp()
source_url = sys.argv[3] if len(sys.argv) > 3 else f'sqlite:///{tmp}/family.db'

seed = subprocess.run([sys.executable, '-W', 'ignore', os.path.join(here, 'seed_family.py'), family_repo, source_url],
                      capture_output=True, text=True)
assert seed.returncode == 0, seed.stderr[-2000:]
vapid = re.search(r'^VAPID (\S+)', seed.stdout, re.M).group(1)
source_counts = ast.literal_eval(re.search(r'^COUNTS (.*)$', seed.stdout, re.M).group(1))
print('family database built:', sum(source_counts.values()), 'rows')

# A fresh single-container install: SQLite file in its data folder, generated secret key
data = os.path.join(tmp, 'appdata')
for k in ('DATABASE_URL', 'SECRET_KEY', 'UPLOAD_FOLDER', 'ASSIGNMENTS_FILE_PATH'):
    os.environ.pop(k, None)
os.environ.update(DATA_PATH=data, PREFERRED_URL_SCHEME='http')
if os.environ.get('TARGET_DATABASE_URL'):
    os.environ['DATABASE_URL'] = os.environ['TARGET_DATABASE_URL']
sys.path.insert(0, ca_repo)
from app import create_app, db
app = create_app('production')
app.config.update(TESTING=True)
app.extensions['mail'].suppress = True
from app.models import *

runner = app.test_cli_runner()
# the copy is refused without confirmation once the target has data... a fresh one has none
res = runner.invoke(args=['copy-database', '--source', source_url])
print(res.output)
assert res.exit_code == 0, (res.output, res.exception)
assert 'Done:' in res.output

with app.app_context():
    for table, n in source_counts.items():
        got = db.session.execute(db.select(db.func.count()).select_from(db.metadata.tables[table])).scalar()
        assert got == n, (table, n, got)
    rob = User.query.filter_by(email='rob@family.test').one()
    assert rob.is_admin and rob.check_password('robpass123') and rob.id == 1
    maya = User.query.filter_by(name='Maya').one()
    assert maya.is_managed and maya.managed_by.name == 'Elizabeth'
    assert User.query.filter_by(email='zoe@family.test').one().is_approved is False
    ann = User.query.filter_by(name='Ann').one()
    assert ann.address == '1 Snow Lane\nNorth Pole' and ann.birthday.month == 12
    items = {i.name: i for i in WishListItem.query.all()}
    assert items['Stand mixer'].price == Decimal('399.99') and items['Wool socks'].purchase.status == 'wrapped'
    assert items['Wool socks'].purchase.is_secret_santa and items['Mystery novel'].price is None
    assert items['Stand mixer'].contributions[0].amount == Decimal('75.25')
    assert items['Plush reindeer'].purchase.purchaser.name == 'Bob'
    ev = ChristmasEvent.query.one()
    assert ev.budget == Decimal('50.00') and ev.lists_lock_date.day == 15 and ev.assignments_sent
    assert SecretSantaAssignment.query.count() == 4 and SantaMessage.query.one().body.endswith('🎄')
    st = AppSettings.query.first()
    assert st.site_name == 'The James Family' and st.vapid_private_key == vapid and st.setup_code is None
    assert st.answer_matches('arthur')
    assert PushSubscription.query.one().user.name == 'Ann'
    # new rows continue after the copied IDs
    u = User(email='new@family.test', name='New'); u.set_password('newpass123'); db.session.add(u); db.session.commit()
    assert u.id > max(x.id for x in User.query.filter(User.id != u.id))

# the copied notification key is the one in use after a restart
app2 = create_app('production')
with app2.app_context():
    assert app2.extensions['vapid'][0] == vapid

# people sign in with their old passwords; no setup page
c = app.test_client()
assert c.get('/dashboard').headers['Location'].endswith('/login?next=%2Fdashboard') or '/login' in c.get('/dashboard').headers['Location']
t = re.search(r'name="csrf-token" content="([^"]+)"', c.get('/login').get_data(as_text=True)).group(1)
r = c.post('/login', data={'email': 'ann@family.test', 'password': 'annpass123', 'csrf_token': t})
assert r.status_code == 302 and '/setup' not in r.headers['Location']
with c.session_transaction() as s:
    s['event_choice_asked'] = True
home = c.get('/dashboard').get_data(as_text=True)
assert 'Dinner at 5!' in home and 'Christmas 2026' in home

# running it again needs confirmation (it would replace everything)
res = runner.invoke(args=['copy-database', '--source', source_url], input='n\n')
assert res.exit_code != 0 and 'Replace ALL' in res.output
with app.app_context():
    assert User.query.filter_by(email='new@family.test').count() == 1, 'declining changes nothing'
res = runner.invoke(args=['copy-database', '--source', source_url, '--yes'])
assert res.exit_code == 0
with app.app_context():
    assert User.query.filter_by(email='new@family.test').count() == 0 and User.query.count() == source_counts['users']

# the source was only read
res = runner.invoke(args=['copy-database', '--source', f'sqlite:///{tmp}/nothing.db', '--yes'])
assert res.exit_code != 0 and 'no users table' in res.output
print('ALL OK')
