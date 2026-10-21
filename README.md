# 🎄 Family Christmas

A private website for your family's wishlists, gift shopping and Secret Santa —
self-hosted in one Docker container, made for Unraid.

- **Wishlists with photos.** Paste a store link and the name, price and picture fill themselves in. Screenshots from shopping apps work too.
- **No spoilers.** Family members mark gifts as bought or chip in on group gifts. The person whose list it is never sees what's been bought for them.
- **Secret Santa.**
  - Draw names with "never pair these two" rules and a budget.
  - Send anonymous questions between a Santa and their person.
  - If someone joins late or drops out, only the people affected get new names.
- **Shopping checklist.** Bought → Wrapped → Given, with a running total.
- **Phone app and notifications.** It installs to the home screen on iPhone and Android, and sends pings for Santa messages, name draws, gift changes and reminders.
- **Organizer tools:**
  - a "Who's ready" board and nudges
  - announcements and an activity log
  - a wishlist lock date
  - copying last year's event
  - a spreadsheet download of everyone's lists
  - "online now"
- **Accounts:**
  - Admins add people, or people request an account. An optional family question lets relatives skip the approval wait.
  - Lists for people without a login, like young kids, are looked after by a parent.
- **Light and dark themes**, with gentle snow.

## Install on Unraid

1. **Apps** tab → search **FamilyChristmas** → **Install**.
2. Leave the defaults, or fill in:
   - **Public URL**: the https address your family will use (see *Phone app & https* below).
   - **Mail settings**: needed for invites, reminders and password resets. With Gmail, use an [App Password](https://support.google.com/accounts/answer/185833).
   - **Gemini API key** (optional): smarter link lookups, AI photo characters and gift poems.
3. Open the **WebUI**. The first page asks for a **setup code**: find it in the container's log (**Docker** tab → app icon → **Logs**). Then create your admin account.
4. Create an event, add your family, and share the link.

Everything is stored in the appdata folder (`/mnt/user/appdata/familychristmas`): the database, photos and generated keys. Back it up with the **Appdata Backup** plugin.

## Other Docker hosts

See [`docker-compose.yml`](docker-compose.yml):

```bash
docker compose up -d
docker compose logs wishlist     # shows the setup code on first start
```

## Settings

| Variable | What it does | Default |
|---|---|---|
| `PUBLIC_URL` | Address people use, e.g. `https://wishlist.example.com`. Used for links in emails and notifications. | `http://localhost:8123` |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS` | Outgoing email server | `smtp.gmail.com`, `587`, `true` |
| `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER` | Email login and From address | — |
| `GEMINI_API_KEY` | Optional AI features | — |
| `REMINDER_HOUR` | Hour (0–23) reminder emails go out | `9` |
| `TZ` | Time zone (Unraid sets it automatically) | `UTC` |
| `DATABASE_URL` | Use PostgreSQL instead of the built-in SQLite file: `postgresql://user:password@host:5432/dbname` | SQLite in `/app/data` |
| `PUID`, `PGID` | Owner of the files in appdata | `99`, `100` |
| `SECRET_KEY` | Signs sign-in cookies. Generated automatically and kept in appdata if you don't set it. | generated |

Everything else is set in the app itself: **Admin → Settings**. That covers the site name, sign-ups and the family question, and reminders.

## Phone app & https

Phones only install the app and allow notifications over **https**. Put the app behind
your reverse proxy (Nginx Proxy Manager, SWAG, Cloudflare Tunnel…), set **Public URL**
to that address, and open it on the phone:

- **iPhone (Safari):** Share → **Add to Home Screen**. Then open it from the home screen and turn on notifications in **My profile**.
- **Android (Chrome):** tap **Install** on the tip that appears.

The plain `http://SERVER-IP:8123` address still works in any browser.

## Updating

Unraid shows **Update available** on the Docker tab. The database is upgraded
automatically when the new version starts. Installed phone apps offer a
"new version — Reload" banner.

## Moving from the docker compose (PostgreSQL) setup

Point `DATABASE_URL` at your existing PostgreSQL database and map your old data folder
(photos) to `/app/data`. Everything carries over: people, passwords, lists, Secret Santa and notification sign-ups.

## Security notes

- There's no built-in admin password. The first admin is created with a one-time setup code from the log.
- Sign-in slows down guessing: 5 wrong passwords for an account, or 20 from one address, means a 15-minute wait.
- The sign-up form has bot protection and limits, and new accounts wait for approval unless they answer the family question.
- Link lookups never fetch addresses on your own network.
- Purchases are never shown to the person they're for, and nobody, admins included, sees who drew whom.

## Development

```bash
pip install -r requirements.txt
DATA_PATH=./data PREFERRED_URL_SCHEME=http flask --app run:app run --port 8123
```

Images are built by GitHub Actions (`.github/workflows/docker.yml`) and published to
`ghcr.io/redrob2/christmas-app-unraid`: `latest` from `main`, plus version tags like `v1.0.0`.
The Unraid template files are drafted in [`unraid/`](unraid/).

## License

[MIT](LICENSE)
