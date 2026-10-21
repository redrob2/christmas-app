# 🎄 Family Christmas App V2 ("Silent Night")

A festive web application for managing family Christmas wishlists and Secret Santa assignments!

![Christmas Theme](https://img.shields.io/badge/theme-Christmas-red)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Flask](https://img.shields.io/badge/flask-3.0-green)
![Docker](https://img.shields.io/badge/docker-ready-blue)

## ✨ Features

### 🧑‍🎄 New: organizer tools (Admin menu)
- **Who's ready** (per event, also linked from Admin overview and event setup): one table showing, for everyone,
  - when they last signed in
  - how many items are on their list
  - how many gifts have been bought for them (a count only, never who bought what; your own row stays hidden)
  - whether they've opened their Secret Santa name (never who they drew)
  - whether notifications are on
- **Joined alerts** - admins get an email and a notification the first time a newly added person signs in.
- **Online now / last seen** - a green dot means someone used the app in the last 5 minutes. Otherwise you see when they were last active ("40 min ago", "Yesterday"). It's shown on **People**, **Who's ready** and an **Online now** card on the overview. This is based on activity rather than sign-in, so people kept signed in with "Remember me" still show correctly.
- **Request an account** - people can create an account from the sign-in page with their name, email, their own password and an optional "who are you?" note.
  - **Family question (optional):** in **Admin → Settings**, switch on *Family question* and enter your own question (e.g. "What is the name of Grandma's first dog?") and the accepted answer(s). Any capitalization works, and you can list several answers separated by commas. Anyone who answers correctly can sign in straight away. Admins are still told, and the person still needs adding to an event. Switch it off and everyone waits for approval.
  - Everyone else waits for an admin. Admins get an email and a notification for each request, and a count shows on the account menu. Approve or decline under **People → Waiting for approval**. Declining deletes the request without emailing them.
  - **New accounts are never added to an event**, whether they're approved, used the family answer, or were added by an admin. An admin adds each person in the event's setup (step 2, People).
  - Spam protection: a hidden form field that catches bots, at most 5 sign-ups per hour from one address, and at most 25 requests waiting at once. The form gives the same answer whether or not an email address already has an account.
  - Turn sign-ups off in **Settings → Let people request an account**.
- **Nudges** - one tap emails and notifies everyone whose list is empty; another resends the welcome email (with a fresh temporary password) to people who haven't signed in. A single person's invite can also be resent from **People**.
- **Announcements** - post a note to everyone in an event ("Gift exchange moved to 3pm"). It shows as a banner on Home, goes out as a notification, and optionally by email.
- **Secret Santa changes after the names went out** - in step 4 of setup, take someone out of the draw or add a latecomer. Only the one or two people affected get a new name (by email and notification); everyone else keeps theirs, and you still never see who has whom.
- **Copy to next year** (Events page) - creates next year's event with the same people, budget, Secret Santa setting and never-pair rules. Dates move forward a year, lists start empty, and last year's event is hidden.
- **Lock wishlists on a date** (event setup → Details) - from that day nobody can add, edit or delete items, so buyers aren't surprised by late changes. Buying still works, and everyone gets a reminder 3 days before.
- **Download lists** (Who's ready page) - a spreadsheet (CSV, opens in Excel or Google Sheets) of everyone's lists with prices, links and notes. A status column shows Bought / Group gift / Available for everyone except you.
- **Lists for people without a login** (e.g. young children) - **People → Add**, switch on *No login* and pick who looks after the list:
  - The person who looks after it adds and edits items from their Home page, and can see what's been bought.
  - Family buy from the list as usual.
  - These people don't draw Secret Santa names and get no emails.
  - **Edit** the person later to give them their own login.
- **Activity log** - people added or removed, events created or changed, names drawn and sent, draw adjustments, nudges and announcements. Purchases and Secret Santa pairs are never recorded.
- **Backup status** on **Settings**: the date and size of the last backup, with a warning on the overview if it's more than a day and a half old. It also shows how many people have notifications on.

### 📱 New: install it as an app, with notifications
- **Installable app** - on a phone, open **https://wishlist.example.com** and add it to the home screen. It gets its own icon, opens full screen without browser bars, and shows a friendly page when there's no signal. Phones show a one-time tip explaining how:
  - **iPhone / iPad (Safari):** Share button (on newer iPhones inside the **•••** menu) → **Add to Home Screen**
  - **Android (Chrome):** tap **Install** on the tip, or ⋮ menu → **Install app**
  - **Computers (Chrome / Edge):** the install icon at the right of the address bar
- **Push notifications** - turn on per device (a card on Home, or **My profile → Notifications**). You get a ping when:
  - your Secret Santa sends you a message, or the person you're buying for replies
  - Secret Santa names are drawn
  - a gift you bought or chipped in on is changed by its owner
  - a reminder goes out (empty list, "N days to go")

  Notifications never say who is whose Secret Santa (they can show on a lock screen). Emails still go out as before. **iPhone:** notifications only work from the home-screen app (iOS 16.4 or newer), not from Safari itself.
- **Share to your wishlist (Android)** - in a store's app (Amazon, Target...) tap **Share → Family Christmas**: the add-item form opens with the link filled in and looked up. Long-pressing the app icon also offers *Add to my wishlist*, *My shopping* and *Secret Santa*.
- **Updates reach installed apps** - after `docker compose up -d --build`, an app left open shows "A new version is ready - Reload" when it's next opened. Pages are never cached on the phone (only the styling, scripts and icons), so nobody sees stale or someone else's data.
- **Home-screen badge** shows unread Secret Santa messages (where the phone supports badges).

**Requirements:** installing and notifications need the **https** address. The LAN address (`http://YOUR-SERVER-IP:8123`) still works in a browser, but phones won't install from it. No extra container or account is needed: the app and the existing `scheduler` send notifications through Apple's, Google's, Mozilla's and Microsoft's free push services. The notification key pair is created automatically on first start and stored in the database (so it is in your backups). Don't delete it: a new key means everyone has to turn notifications on again.

### 🌙 New in V2 - a redesign
- **New look ("Silent Night")** - night-sky background with warm cream cards; cranberry for the main action, gold for "this is yours", pine green only for buy/done. **Dark by default**, light mode one tap away (sun/moon button; remembered per device)
- **Simpler navigation** - four always-visible tabs: **Home, Wishlists, My shopping, Secret Santa**; a **bottom tab bar on phones**; admin pages live in the account menu
- **Home** replaces Events: the current event's countdown, your Secret Santa (with budget bar), your list, your shopping progress, and everyone's lists ("Nothing bought yet" flags who still needs a gift)
- **Wishlists as photo cards** with filters (Available, Under $50, Top picks, Group gifts) and sorting
- **Wishlists tab** with a "Still need a gift" filter
- **Secret Santa page** with a reveal card, budget bar and two anonymous chat threads
- **Guided admin setup** - Details → People → Secret Santa → Draw & send, all on one page
- **Line icons** (Lucide) instead of Font Awesome, and **photo or initials avatars** instead of holiday profile icons
- Readable fonts: Poppins headings, Nunito text, Dancing Script for the app name and event titles


### 🆕 New in V6
- **Prices & budgets** - optional price on every wishlist item; a Secret Santa spending limit per event
- **Group gifts** - "Chip In" on pricey items (with an optional amount); the recipient never sees it
- **My Shopping** - one page with everything you bought or chipped in on, with Bought → Wrapped → Given tracking and a budget check for your Secret Santa pick
- **Anonymous Santa Q&A** - Secret Santas can ask their recipient questions; the recipient replies without ever learning who asked (email notifications both ways)
- **Copy from a past list** - pull last year's unpurchased items into this year's wishlist in one click
- **Reminder emails** - "your list is empty" and "N days to go" reminders, sent once per person by the `scheduler` service (configure in Admin → Settings)
- **Dark mode** - moon/sun toggle in the menu bar; follows your device setting by default
- **Site name everywhere** - Admin → Settings → Site Name now drives the menu, page titles and emails
- **Security** - CSRF protection on every form, safe link handling, no purchase hints leaked to list owners

### 📜 AI Gift Poems (NEW in V5!)
- After marking an item as purchased, generate a **cryptic poem** about the gift!
- Uses Google Gemini AI to create 10-20 line poems with hints about the gift and recipient
- Perfect for the family gift-giving game where wrapped gifts have poem clues
- **Poems are saved** so you can view them anytime
- **Regenerate up to 10 times** if you want a different poem
- Copy the poem with one click to use on gift tags

### 🔗 Clickable Family Members (NEW in V5!)
- Click on a family member's name or icon in the Family Wishlists table
- Takes you directly to their wishlist (same as View button)
- More intuitive navigation

### 🦌 AI Profile Photos
- Upload a photo and get transformed into a **Rudolph the Red-Nosed Reindeer** style character!
- Uses Google Gemini AI (Nano Banana) for stop-motion style transformation
- Full-size 500x500 AI character image with click-to-view
- Icon-sized version for tables and lists
- Fallback holiday icons still available

### 👥 User Management
- Admin-only account creation with email notifications
- Temporary passwords with required change on first login
- Password reset functionality (admin and self-service)
- Role-based access (Admin / User)
- Profile with birthday, address, and about me sections

### 🎁 Wishlist Management
- Create and manage personal wishlists for each Christmas event
- Add items with details: name, URL, color, size, notes, and **photos**
- Priority levels for items
- Mark items as purchased (visible to everyone except the list owner)
- Edit notifications sent to purchasers when items are modified

### 🎅 Secret Santa
- Random assignment algorithm that:
  - Prevents self-assignment
  - Respects exclusion pairs (e.g., spouses) - **per event**
  - Opt-out option for members who don't want to participate
  - Attempts to avoid repeat assignments from previous years
- Email notifications for assignments
- Assignments saved to file for backup
- Admin cannot see who is assigned to whom (only notification status)

### 📅 Event Management
- Multiple events per year
- **Event date** with countdown ("X days until Christmas!")
- Participant management
- Active/inactive event status

## 🚀 Quick Start (Unraid / Docker)

### Prerequisites
- Docker and Docker Compose installed
- Port 8123 available (or modify docker-compose.yml)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/redrob2/christmas-app-unraid.git
   cd christmas-app
   ```

2. **Create environment file:**
   ```bash
   cp .env.example .env
   ```

3. **Edit the `.env` file with your settings:**
   ```bash
   nano .env
   ```
   
   **Important settings to change:**
   - `SECRET_KEY`: Generate a secure random string
   - `MAIL_PASSWORD`: Your Gmail App Password
   - `GEMINI_API_KEY`: Your Gemini API key

4. **Start the application:**
   ```bash
   docker compose up -d --build
   ```

5. **Access the application:**
   - Open `http://your-server-ip:8123`
   - Default admin login (created only on a brand-new database):
     - Email: `admin@christmas.app`
     - Password: `admin123`
   - **Change this password immediately!**

### Unraid-Specific Setup

1. Copy the `christmas-app` folder to your Unraid server (e.g., `/mnt/user/appdata/christmas-app/`)

2. In Unraid terminal:
   ```bash
   cd /mnt/user/appdata/christmas-app
   docker compose up -d --build
   ```

3. For persistent access, you can create a custom Docker container in Unraid's Docker tab using the docker-compose configuration.

### Port Forwarding for External Access

To access it from your own domain:
1. Forward port 8123 (or your chosen port) on your router to your Unraid server
2. Set up a reverse proxy (like Nginx Proxy Manager) for SSL
3. Point your domain to your public IP

## 📧 Email Configuration (Gmail)

1. Enable 2-Factor Authentication on your Gmail account
2. Generate an App Password:
   - Go to Google Account → Security → 2-Step Verification → App passwords
   - Create a new app password for "Mail"
3. Use this App Password in your `.env` file

## 🔧 Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `FLASK_ENV` | Environment mode | `production` |
| `SECRET_KEY` | Flask secret key | (generate one!) |
| `DATABASE_URL` | PostgreSQL connection string | (see docker-compose) |
| `MAIL_SERVER` | SMTP server | `smtp.gmail.com` |
| `MAIL_PORT` | SMTP port | `587` |
| `MAIL_USERNAME` | Email username | - |
| `MAIL_PASSWORD` | Email password/app password | - |
| `GEMINI_API_KEY` | Google Gemini API key for AI photos | - |
| `VAPID_SUBJECT` | Contact for push services (`https://...` or `mailto:...`) | `https://` + `SERVER_NAME_FOR_EMAILS` |
| `VAPID_PRIVATE_KEY` | Only to supply your own notification key (normally generated and stored in the database) | - |

### Admin Settings (In-App)

Once logged in as admin, go to **Admin → Settings** to configure:
- Site name
- Reminder emails (on/off, how many days before the event)

Settings also shows the last backup and how many people have notifications on. The backup folder is mounted read-only into the `web` container (`/app/backups`) for this. Run `docker compose up -d` once after updating so the mount is added.

Email (SMTP) settings live in `.env` and are shown read-only on the Settings page.

### Services

| Service | What it does |
|---------|--------------|
| `web` | The app (gunicorn on port 8123) |
| `scheduler` | Sends reminder emails and notifications daily at `REMINDER_HOUR` |
| `db` | PostgreSQL 15 |
| `backup` | Daily database + uploads backup to `./backups` |

Send due reminders right now: `docker compose exec scheduler flask --app run:app send-reminders`

## 📁 Project Structure

```
christmas-app/
├── app/
│   ├── __init__.py          # App factory
│   ├── models.py            # Database models
│   ├── gemini_service.py    # AI photo transformation
│   └── routes/
│       ├── auth.py          # Authentication
│       ├── main.py          # Dashboard
│       ├── admin.py         # Admin functions
│       ├── events.py        # Event viewing
│       ├── profile.py       # User profiles & photo upload
│       ├── wishlist.py      # Wishlist management
│       └── secretsanta.py   # Secret Santa logic
├── templates/               # Jinja2 templates
├── static/
│   ├── css/christmas.css    # Christmas theme
│   └── js/christmas.js      # Frontend JavaScript
├── config.py                # Configuration
├── run.py                   # Entry point
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 🎨 Theme

The app features a festive Christmas theme with:
- Red and green color scheme
- Animated snowflakes
- Holiday icons and decorations
- Responsive design for mobile and desktop

## 🔒 Security Notes

- Passwords are hashed using Werkzeug's security functions
- Session-based authentication with Flask-Login
- Admin-only functions protected by decorators
- Secret Santa assignments hidden from admin view

## 📋 Default Admin Account

- **Email:** `admin@christmas.app`
- **Password:** `admin123`

⚠️ **Change this immediately after first login!**

## 🐛 Troubleshooting

### Database Connection Issues
```bash
# Check if database container is running
docker-compose ps

# View logs
docker-compose logs db
```

### Email Not Sending
1. Verify Gmail App Password is correct
2. Check that 2FA is enabled on Gmail
3. View application logs: `docker-compose logs web`

### App won't install / notifications missing
1. Use the **https://wishlist.example.com** address; installing doesn't work from the plain `http://` LAN address.
2. iPhone: open the app **from the home-screen icon**, then **My profile → Notifications → Turn on**. In Safari itself the button is not offered.
3. If you chose "Don't allow" earlier, allow notifications again in the phone's settings (iPhone: Settings → Notifications → Family Christmas; Android: long-press the app icon → App info → Notifications), then use **Send a test**.
4. Push errors are logged with a `[push]` prefix: `docker compose logs web scheduler | grep push`
5. If the site sits behind a proxy (Nginx Proxy Manager, Cloudflare), make sure `/sw.js` and `/manifest.webmanifest` aren't cached by it. The app already marks both as "don't cache".

### Reset Everything
```bash
docker compose down
rm -rf /mnt/user/appdata/christmas-app-db /mnt/user/appdata/christmas-app-data  # ⚠️ deletes ALL data!
docker compose up -d --build
```

## 📂 Where the data lives

| What | Folder on Unraid (set in `.env`) |
|------|------|
| PostgreSQL database | `DB_DIR` = `/mnt/user/appdata/christmas-app-db` |
| Uploads + Secret Santa files | `DATA_DIR` = `/mnt/user/appdata/christmas-app-data` |
| Nightly backups | `BACKUP_DIR` = `./backups` |

These are plain folders outside `docker.img`, so they survive `docker compose down`,
image rebuilds and even deleting/recreating `docker.img`. Set the **appdata** share to
*Primary storage: cache, Secondary: none* so the mover never moves live database files,
and never edit or delete files in `DB_DIR` while the stack is running.

## 🛠️ Maintenance (safe shutdown)

The database container is given 2 minutes to shut down cleanly, so a normal
`docker compose down` always leaves it in a consistent state.

```bash
cd /mnt/user/appdata/christmas-app
docker compose exec backup sh /backup.sh once   # fresh backup first
docker compose down
# ...maintenance...
docker compose up -d --build
docker compose ps                               # all services should be "healthy"/"running"
```

## 💾 Backups & restore

The `backup` service dumps the database and archives uploads/assignments at startup
and then every 24h into `./backups` (keeps 14 days; see `BACKUP_*` in `.env`).
Copy them off-server too (e.g. with the Unraid backup plugin).

Restore the database from a dump:
```bash
docker compose stop web
docker compose exec -T db pg_restore -U christmas -d christmas_app --clean --if-exists < backups/db-YYYYMMDD-HHMMSS.dump
docker compose start web
```

Restore uploads:
```bash
docker compose run --rm -v "$PWD/backups:/backups" --entrypoint sh web -c "tar -xzf /backups/files-YYYYMMDD-HHMMSS.tar.gz -C /app/data"
```

## 📜 License

MIT License - Feel free to use for your family!

## 🤝 Contributing

This is a personal family project, but feel free to fork and customize for your own family!

---

Made with ❤️ for the holidays! 🎄🎅🎁
