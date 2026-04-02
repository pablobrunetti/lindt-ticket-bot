# Lindt Ticket Bot

The [Lindt Home of Chocolate](https://www.lindt-home-of-chocolate.com/) in Kilchberg, Switzerland is one of the world's largest chocolate museums. Tickets are sold through the SecuTix platform and popular time slots sell out quickly — sometimes weeks in advance.

This bot continuously polls the SecuTix availability endpoint and sends you an instant notification the moment a slot opens up, so you can book before anyone else.

## How it works

The bot calls the internal AJAX endpoint used by the booking page to fetch available time slots for a given date. It parses the HTML response to identify slots that have a "Select" button and are not marked as sold out. When a new slot is found that hasn't been notified before, it sends an alert and saves the slot to a local state file to avoid duplicate notifications.

## Notifications

Supports two channels — you can enable one or both:

- **Telegram** — instant push notification via a Telegram bot
- **Gmail** — email via SMTP with an App Password

## Setup

**1. Clone and install dependencies**

```bash
git clone https://github.com/pablobrunetti/lindt-ticket-bot.git
cd lindt-ticket-bot
python -m venv .venv
source .venv/bin/activate
pip install requests python-dotenv
```

**2. Configure credentials**

```bash
cp .env.example .env
```

Edit `.env` with your Telegram credentials:

```
TELEGRAM_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

To get these:
- Token: talk to [@BotFather](https://t.me/BotFather) on Telegram → `/newbot`
- Chat ID: talk to [@userinfobot](https://t.me/userinfobot) on Telegram

**3. Set target dates**

Edit the `CONFIG` dict at the top of `bot_lindt.py`:

```python
"target_dates": ["2026-04-10", "2026-04-11"],  # specific dates
# or leave empty [] to monitor the next N days:
"days_ahead": 60,
```

**4. Run**

```bash
# Daemon mode — loops every check_interval_seconds (default: 3 min)
python bot_lindt.py

# One-shot mode — check once and exit (ideal for cron)
python bot_lindt.py --once
```

**Cron example** (every 5 minutes):
```
*/5 * * * * /path/to/.venv/bin/python /path/to/bot_lindt.py --once
```

## Gmail setup (optional)

Fill in the email fields in `CONFIG` directly in `bot_lindt.py`:

```python
"email_from": "you@gmail.com",
"email_password": "your_app_password",
"email_to": "you@gmail.com",
```

Gmail requires an [App Password](https://myaccount.google.com/apppasswords) — not your regular password.
