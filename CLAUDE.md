# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Python bot (`bot_lindt.py`) that polls the Lindt Home of Chocolate ticket site (SecuTix platform) for available time slots and sends notifications via Telegram and/or Gmail when new slots appear.

## Running the bot

```bash
# Activate the virtual environment
source .venv/bin/activate

# Run in daemon mode (infinite loop, checks every CONFIG["check_interval_seconds"])
python bot_lindt.py

# Run once and exit (cron-friendly)
python bot_lindt.py --once
```

## Configuration

All runtime config is in the `CONFIG` dict at the top of `bot_lindt.py`:

- `target_dates`: list of `YYYY-MM-DD` strings to monitor; if empty, monitors the next `days_ahead` days
- `check_interval_seconds`: polling interval (default 180s)
- `telegram_token` / `telegram_chat_id`: read from `.env` via `TELEGRAM_TOKEN` / `TELEGRAM_CHAT_ID`
- `email_from` / `email_password` / `email_to`: Gmail SMTP credentials (App Password required)
- `state_file`: path to `lindt_bot_state.json` which persists already-notified slots

## Architecture

The bot has three layers:

1. **Availability check** (`check_availability`): GETs the SecuTix AJAX endpoint (`/ajax/selection/timeslots`) with date and `productId` params, parses the returned HTML fragment with regex to find `<li>` blocks that have a "Select" button and are not marked sold out.

2. **State tracking** (`load_state`/`save_state`): A JSON file stores `notified_slots` as a list of `"YYYY-MM-DD_HH:MM"` keys to avoid duplicate notifications across runs.

3. **Notification** (`notify`, `send_telegram`, `send_email`): Telegram uses the Bot API directly via `requests.post`; email uses `smtplib.SMTP_SSL` to Gmail port 465.

## Dependencies

Actual runtime dependencies (not the full system freeze in `requirements.txt`):
- `requests`
- `python-dotenv`

Install with:
```bash
pip install requests python-dotenv
```
