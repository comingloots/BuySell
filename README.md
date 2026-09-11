# Telegram Join Request Verifier Bot

A Telegram bot that listens to `chat_join_request` updates and checks the requesting user's verification status in SQLite.

## Critical behavior

**The bot does NOT accept or reject join requests.**

It never calls:

- `approveChatJoinRequest`
- `declineChatJoinRequest`

The channel Owner/Admin remains responsible for the final Accept/Reject action in Telegram.

Flow:

```text
User sends Join Request
        ↓
Bot receives chat_join_request
        ↓
Bot checks SQLite verified_users
        ↓
Verified? → send verified message
Not verified? → log request only
        ↓
Owner/Admin manually Accept/Reject
```

## Features

- Owner
- Add/remove admins
- Add/delete channels
- Welcome message editing
- Verified message editing
- Verified user list
- SQLite stats
- Broadcast to verified users
- `/admin` panel
- `.env` token/owner configuration
- VPS deployment with systemd
- `chat_join_request` based verification
- No automated approval/rejection

## 1. Create the bot

Open @BotFather in Telegram and create a bot.

Put the token in `.env`.

Get your numeric Telegram user ID and put it in `OWNER_ID`.

## 2. Telegram permissions

For every channel where you want to receive join requests:

1. Add the bot as an administrator.
2. Give it permission to manage join requests if Telegram exposes that permission.
3. Enable join requests for the channel's invite link.

The bot only observes/processes the join-request update. It does not make the final moderation decision.

## 3. Install

Python 3.11+ is recommended.

```bash
git clone <your-repo>
cd telegram_join_verifier

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env

python bot.py
```

## 4. Verify users

The verification source is the SQLite table:

```text
verified_users
```

A user is verified when their Telegram numeric user ID exists in that table.

You can insert users manually:

```bash
sqlite3 data/bot.sqlite3
```

Then:

```sql
INSERT OR REPLACE INTO verified_users(user_id, name, username)
VALUES (123456789, 'Example User', 'exampleusername');
```

Or use the included helper script:

```bash
python manage.py verify 123456789 --name "Example User" --username "exampleusername"
python manage.py unverify 123456789
python manage.py list
```

## 5. Admin panel

Send:

```text
/admin
```

Owner can:

- Add/remove admins
- Manage channels
- Edit welcome message
- Edit verified message
- View verified users
- View stats
- Broadcast to verified users

Additional admins cannot manage other admins.

## 6. VPS deployment

Install dependencies:

```bash
sudo apt update
sudo apt install -y python3 python3-venv sqlite3
```

Create a service:

```bash
sudo nano /etc/systemd/system/join-verifier.service
```

Example:

```ini
[Unit]
Description=Telegram Join Request Verifier
After=network.target

[Service]
Type=simple
User=YOUR_LINUX_USER
WorkingDirectory=/opt/telegram_join_verifier
ExecStart=/opt/telegram_join_verifier/.venv/bin/python /opt/telegram_join_verifier/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable join-verifier
sudo systemctl start join-verifier

sudo systemctl status join-verifier
```

Logs:

```bash
journalctl -u join-verifier -f
```

## Security

- Never commit `.env`.
- Keep the bot token private.
- Keep the SQLite database private.
- Use a non-root Linux user for the systemd service.
- Restrict VPS SSH access appropriately.

## Notes

This is a polling-based Aiogram bot. Telegram sends join-request updates to the bot, and the handler checks the database.

The database check is intentionally simple and local. If verification later needs to come from an external API, replace `Database.is_verified()` with the required verification service.

## License

Use and modify as needed.


## Premium-style UI

The upgraded bot supports:

- Photo + caption
- HTML formatting
- Normal emoji
- Telegram custom/premium emoji when Telegram makes the entity available to the bot
- Inline URL buttons
- Separate Welcome and Verified message media
- Admin-side message/button/photo configuration

Button format:

```text
🔒 Join Channel|https://t.me/example ; ✅ Claim|https://example.com
```

Use `/admin` → `🎨 Premium UI`.

### Important

Telegram Premium does not magically give a bot unlimited premium emoji capabilities. Custom emoji are Telegram entities with Telegram-side availability/permissions. Use them in messages/captions where supported.

The bot still **never accepts or rejects a join request**.
