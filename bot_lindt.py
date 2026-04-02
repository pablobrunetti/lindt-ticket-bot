"""
Lindt Home of Chocolate – Availability Monitoring Bot
======================================================
Checks time slot availability on the ticketing system (SecuTix)
and sends a notification via Telegram and/or e-mail when a slot opens up.

Quick setup:
  1. Edit the CONFIG section below
  2. pip install requests python-dotenv
  3. python bot_lindt.py

Cron mode (check every 5 min):
  */5 * * * * /usr/bin/python3 /path/to/bot_lindt.py --once
"""

import os
import requests
import smtplib
import json
import time
import logging
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
#  CONFIG – edit here
# ─────────────────────────────────────────────
CONFIG = {
    # Dates you want to monitor (format YYYY-MM-DD)
    # Leave empty [] to monitor the next `days_ahead` days
    "target_dates": [
        "2026-03-20",
        "2026-03-21",
        "2026-03-22"
    ],

    # How many days ahead to monitor (used when target_dates is empty)
    "days_ahead": 60,

    # Interval between checks in seconds (default: 3 min)
    "check_interval_seconds": 180,

    # ── Telegram ──────────────────────────────
    # Leave blank to disable
    # How to create: talk to @BotFather on Telegram → /newbot
    # Chat ID: talk to @userinfobot on Telegram
    "telegram_token": os.getenv("TELEGRAM_TOKEN", ""),
    "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),

    # ── E-mail (Gmail) ────────────────────────
    # Leave blank to disable
    # For Gmail: enable "App Passwords" at myaccount.google.com/security
    "email_from": "",
    "email_password": "",   # App Password (not your regular password)
    "email_to": "",

    # ── State file ────────────────────────────
    # Stores which slots have already been notified to avoid duplicates
    "state_file": "lindt_bot_state.json",
}

# ─────────────────────────────────────────────
#  SecuTix URLs (Lindt)
# ─────────────────────────────────────────────
BASE_URL = "https://tickets.lindt-home-of-chocolate.com"
PRODUCT_ID = "101502126146"

# Real AJAX endpoint (discovered via the browser Network tab)
AJAX_URL = f"{BASE_URL}/ajax/selection/timeslots"

# Booking link to include in the notification
BOOKING_URL = (
    f"{BASE_URL}/selection/timeslotpass"
    f"?productId={PRODUCT_ID}&lang=en"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "X-Secutix-Host": "tickets.lindt-home-of-chocolate.com",
    "Referer": BASE_URL,
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("lindt_bot")


# ─────────────────────────────────────────────
#  Persistent state
# ─────────────────────────────────────────────
def load_state() -> set:
    try:
        with open(CONFIG["state_file"]) as f:
            return set(json.load(f).get("notified_slots", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_state(notified: set):
    with open(CONFIG["state_file"], "w") as f:
        json.dump({"notified_slots": list(notified)}, f)


# ─────────────────────────────────────────────
#  Availability check
# ─────────────────────────────────────────────
def get_target_dates() -> list[str]:
    if CONFIG["target_dates"]:
        return CONFIG["target_dates"]
    today = date.today()
    return [
        (today.replace(day=1) if False else
         date.fromordinal(today.toordinal() + i)).isoformat()
        for i in range(CONFIG["days_ahead"])
    ]


def check_availability(target_date: str) -> list[dict]:
    """
    Calls the real SecuTix AJAX endpoint:
      GET /ajax/selection/timeslots?year=YYYY&month=M&day=D&productId=...
    Returns a partial HTML fragment with the time slots for the day.
    Available slots have a "Select" link; sold-out slots have the "soldOut" class or no link.
    """
    import re
    slots = []

    d = date.fromisoformat(target_date)
    params = {
        "year": d.year,
        "month": d.month,
        "day": d.day,
        "productId": PRODUCT_ID,
        "rateInsteadOfTimeslotsTable": "false",
        "_": int(time.time() * 1000),  # cache-buster matching browser behaviour
    }

    try:
        r = requests.get(AJAX_URL, params=params, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            log.warning(f"AJAX returned {r.status_code} for {target_date}")
            return slots

        html = r.text

        # Each slot is a <li> element in the returned HTML fragment.
        # AVAILABLE slot: contains an <a> with "Select" (or a form submit)
        # SOLD OUT slot:  contains the "soldOut" class or "Sold out" text / no Select link
        #
        # Extract all <li>...</li> blocks
        li_blocks = re.findall(r'<li\b[^>]*>.*?</li>', html, re.DOTALL | re.IGNORECASE)

        for block in li_blocks:
            # Extract the HH:MM time
            time_match = re.search(r'\b(\d{2}:\d{2})\b', block)
            if not time_match:
                continue
            slot_time = time_match.group(1)

            # Skip if marked as sold out
            if re.search(r'sold.?out|unavailable|complet', block, re.IGNORECASE):
                log.debug(f"{target_date} {slot_time} → SOLD OUT")
                continue

            # Only count if a Select link/button is present
            if not re.search(r'Select|submit', block, re.IGNORECASE):
                log.debug(f"{target_date} {slot_time} → no Select button, skipped")
                continue

            slots.append({"date": target_date, "time": slot_time, "remaining": None})
            log.debug(f"{target_date} {slot_time} → AVAILABLE")

    except Exception as e:
        log.warning(f"Error checking {target_date}: {e}")

    return slots


# ─────────────────────────────────────────────
#  Notifications
# ─────────────────────────────────────────────
def send_telegram(message: str):
    token = CONFIG.get("telegram_token")
    chat_id = CONFIG.get("telegram_chat_id")
    if not token or not chat_id:
        log.debug("Telegram not configured: token/chat_id missing")
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        r = requests.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
        }, timeout=10)
        if r.status_code == 200:
            log.info("Telegram: notification sent ✓")
        else:
            log.warning(f"Telegram error: {r.status_code} {r.text}")
    except Exception as e:
        log.error(f"Telegram failed: {e}")


def send_email(subject: str, body: str):
    sender = CONFIG["email_from"]
    password = CONFIG["email_password"]
    recipient = CONFIG["email_to"]
    if not sender or not password or not recipient:
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = recipient
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
        log.info("Email: notification sent ✓")
    except Exception as e:
        log.error(f"Email failed: {e}")


def notify(slots: list[dict]):
    lines = []
    for s in slots:
        rem = f" ({s['remaining']} slots remaining)" if s.get("remaining") else ""
        lines.append(f"  📅 {s['date']}  🕐 {s['time']}{rem}")

    body = (
        "🍫 <b>Lindt Home of Chocolate – Slots Available!</b>\n\n"
        + "\n".join(lines)
        + f"\n\n🔗 <a href='{BOOKING_URL}'>Book your ticket</a>"
    )

    send_telegram(body)
    send_email(
        subject="🍫 Lindt – Slots available!",
        body=body.replace("<b>", "").replace("</b>", "")
                  .replace("<a href='", "").replace("'>Book your ticket</a>", "")
    )


# ─────────────────────────────────────────────
#  Main loop
# ─────────────────────────────────────────────
def run_once():
    """Runs a single check round and returns any newly found slots."""
    notified = load_state()
    new_slots = []

    dates = get_target_dates()
    log.info(f"Checking {len(dates)} dates...")

    for d in dates:
        slots = check_availability(d)
        for slot in slots:
            key = f"{slot['date']}_{slot['time']}"
            if key not in notified:
                new_slots.append(slot)
                notified.add(key)

    if new_slots:
        log.info(f"🎉 {len(new_slots)} new slot(s) found!")
        log.info(new_slots)
        notify(new_slots)
        save_state(notified)
    else:
        log.info("No new slots found.")

    return new_slots


def run_loop():
    """Loops indefinitely, checking every check_interval_seconds."""
    log.info("Bot started. Press Ctrl+C to stop.")
    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            log.info("Bot stopped.")
            break
        except Exception as e:
            log.error(f"Unexpected error: {e}")

        interval = CONFIG["check_interval_seconds"]
        log.info(f"Next check in {interval//60} min...")
        time.sleep(interval)


# ─────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    if "--once" in sys.argv:
        # Cron mode: run once and exit
        run_once()
    else:
        # Daemon mode: infinite loop
        run_loop()
