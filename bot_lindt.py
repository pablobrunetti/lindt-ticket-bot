"""
Lindt Home of Chocolate – Bot de Monitoramento de Vagas
========================================================
Verifica disponibilidade de horários no sistema de tickets (SecuTix)
e envia notificação via Telegram e/ou e-mail quando encontrar vaga.

Configuração rápida:
  1. Edite a seção CONFIG abaixo
  2. pip install requests python-telegram-bot
  3. python lindt_bot.py

Modo cron (checar a cada 5 min):
  */5 * * * * /usr/bin/python3 /caminho/lindt_bot.py
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
#  CONFIG – edite aqui
# ─────────────────────────────────────────────
CONFIG = {
    # Datas que você quer monitorar (formato YYYY-MM-DD)
    # Deixe vazio [] para monitorar os próximos 60 dias
    "target_dates": [
        "2026-03-20",
        "2026-03-21",
        "2026-03-22"
    ],

    # Quantos dias à frente monitorar (usado se target_dates estiver vazio)
    "days_ahead": 60,

    # Intervalo entre checagens em segundos (padrão: 5 min)
    "check_interval_seconds": 180,

    # ── Telegram ──────────────────────────────
    # Deixe em branco para desativar
    # Como criar: fale com @BotFather no Telegram → /newbot
    # Chat ID: fale com @userinfobot no Telegram
    "telegram_token": os.getenv("TELEGRAM_TOKEN", ""),
    "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),

    # ── E-mail (Gmail) ────────────────────────
    # Deixe em branco para desativar
    # Para Gmail: ative "App Passwords" em myaccount.google.com/security
    "email_from": "",
    "email_password": "",   # App Password (não a senha normal)
    "email_to": "",

    # ── Arquivo de estado ─────────────────────
    # Guarda quais datas já foram notificadas para não spammar
    "state_file": "lindt_bot_state.json",
}

# ─────────────────────────────────────────────
#  URLs SecuTix (Lindt)
# ─────────────────────────────────────────────
BASE_URL = "https://tickets.lindt-home-of-chocolate.com"
PRODUCT_ID = "101502126146"

# Endpoint AJAX real (descoberto via Network tab)
AJAX_URL = f"{BASE_URL}/ajax/selection/timeslots"

# Link de compra para incluir na notificação
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
#  Estado persistente
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
#  Checagem de disponibilidade
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
    Chama o endpoint AJAX real do SecuTix:
      GET /ajax/selection/timeslots?year=YYYY&month=M&day=D&productId=...
    Retorna HTML parcial com os slots do dia.
    Slots disponíveis têm link "Select"; slots lotados têm classe "soldOut" ou sem link.
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
        "_": int(time.time() * 1000),  # cache-buster igual ao browser
    }

    try:
        r = requests.get(AJAX_URL, params=params, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            log.warning(f"AJAX retornou {r.status_code} para {target_date}")
            return slots

        html = r.text

        # Cada slot é um <li> no HTML parcial retornado.
        # Slot DISPONÍVEL: contém um <a> com "Select" (ou submissão de form)
        # Slot LOTADO:     contém classe "soldOut" ou texto "Sold out" / sem link Select
        #
        # Extrai todos os blocos <li>...</li>
        li_blocks = re.findall(r'<li\b[^>]*>.*?</li>', html, re.DOTALL | re.IGNORECASE)

        for block in li_blocks:
            # Pega o horário HH:MM
            time_match = re.search(r'\b(\d{2}:\d{2})\b', block)
            if not time_match:
                continue
            slot_time = time_match.group(1)

            # Descarta se está marcado como sold out
            if re.search(r'sold.?out|unavailable|complet', block, re.IGNORECASE):
                log.debug(f"{target_date} {slot_time} → LOTADO")
                continue

            # Só conta se tem link/botão de selecção
            if not re.search(r'Select|submit', block, re.IGNORECASE):
                log.debug(f"{target_date} {slot_time} → sem botão Select, ignorado")
                continue

            slots.append({"date": target_date, "time": slot_time, "remaining": None})
            log.debug(f"{target_date} {slot_time} → DISPONÍVEL")

    except Exception as e:
        log.warning(f"Erro ao checar {target_date}: {e}")

    return slots


# ─────────────────────────────────────────────
#  Notificações
# ─────────────────────────────────────────────
def send_telegram(message: str):
    token = CONFIG.get("telegram_token")
    chat_id = CONFIG.get("telegram_chat_id")
    if not token or not chat_id:
        log.debug("Telegram não configurado: token/chat_id ausente")
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        r = requests.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
        }, timeout=10)
        if r.status_code == 200:
            log.info("Telegram: notificação enviada ✓")
        else:
            log.warning(f"Telegram erro: {r.status_code} {r.text}")
    except Exception as e:
        log.error(f"Telegram falhou: {e}")


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
        log.info("Email: notificação enviada ✓")
    except Exception as e:
        log.error(f"Email falhou: {e}")


def notify(slots: list[dict]):
    lines = []
    for s in slots:
        rem = f" ({s['remaining']} vagas)" if s.get("remaining") else ""
        lines.append(f"  📅 {s['date']}  🕐 {s['time']}{rem}")

    body = (
        "🍫 <b>Lindt Home of Chocolate – Vagas Disponíveis!</b>\n\n"
        + "\n".join(lines)
        + f"\n\n🔗 <a href='{BOOKING_URL}'>Comprar ingresso</a>"
    )

    send_telegram(body)
    send_email(
        subject="🍫 Lindt – Vagas disponíveis!",
        body=body.replace("<b>", "").replace("</b>", "")
                  .replace("<a href='", "").replace("'>Comprar ingresso</a>", "")
    )


# ─────────────────────────────────────────────
#  Loop principal
# ─────────────────────────────────────────────
def run_once():
    """Faz uma rodada de checagem e retorna os slots novos encontrados."""
    notified = load_state()
    new_slots = []

    dates = get_target_dates()
    log.info(f"Checando {len(dates)} datas...")

    for d in dates:
        slots = check_availability(d)
        for slot in slots:
            key = f"{slot['date']}_{slot['time']}"
            if key not in notified:
                new_slots.append(slot)
                notified.add(key)

    if new_slots:
        log.info(f"🎉 {len(new_slots)} slot(s) novo(s) encontrado(s)!")
        log.info(new_slots)
        notify(new_slots)
        save_state(notified)
    else:
        log.info("Nenhuma vaga nova encontrada.")

    return new_slots


def run_loop():
    """Fica em loop checando a cada check_interval_seconds."""
    log.info("Bot iniciado. Pressione Ctrl+C para parar.")
    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            log.info("Bot encerrado.")
            break
        except Exception as e:
            log.error(f"Erro inesperado: {e}")

        interval = CONFIG["check_interval_seconds"]
        log.info(f"Próxima checagem em {interval//60} min...")
        time.sleep(interval)


# ─────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    if "--once" in sys.argv:
        # Modo cron: roda uma vez e sai
        run_once()
    else:
        # Modo daemon: loop infinito
        run_loop()