"""Multi-channel alert delivery: WhatsApp (Twilio) and/or Telegram."""

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)


# ── WhatsApp via Twilio ────────────────────────────────────────────────────────

def _send_whatsapp(message: str) -> None:
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    from_number = os.environ.get("TWILIO_WHATSAPP_FROM", "")
    to_numbers_raw = os.environ.get("TWILIO_WHATSAPP_TO", "")

    if not all([account_sid, auth_token, from_number, to_numbers_raw]):
        return

    to_numbers = [n.strip() for n in to_numbers_raw.split(",") if n.strip()]
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"

    for to in to_numbers:
        try:
            resp = requests.post(
                url,
                auth=(account_sid, auth_token),
                data={"From": from_number, "To": to, "Body": message},
                timeout=15,
            )
            resp.raise_for_status()
            logger.info("WhatsApp alert sent to %s", to)
        except requests.RequestException as exc:
            logger.error("WhatsApp send failed to %s: %s", to, exc)


# ── Telegram ───────────────────────────────────────────────────────────────────

def _send_telegram(message: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=15,
        )
        resp.raise_for_status()
        logger.info("Telegram alert sent.")
    except requests.RequestException as exc:
        logger.error("Telegram send failed: %s", exc)


# ── Public API ─────────────────────────────────────────────────────────────────

def send_alert(message: str) -> None:
    """Dispatch the alert to every configured channel."""
    whatsapp_configured = bool(os.environ.get("TWILIO_ACCOUNT_SID"))
    telegram_configured = bool(os.environ.get("TELEGRAM_BOT_TOKEN"))

    if not whatsapp_configured and not telegram_configured:
        logger.warning("No notification channel configured. Printing alert to console.")
        print(f"\n[ALERT]\n{message}\n")
        return

    _send_whatsapp(message)
    _send_telegram(message)


def format_alert(
    watch_name: str,
    offer,
    alert_type: str,
    prev_price: Optional[float],
) -> str:
    stops_text = "Non-stop" if offer.stops == 0 else f"{offer.stops} stop(s)"

    lines = [
        f"*Flight Alert — {watch_name}*",
        f"Route: {offer.origin} -> {offer.destination}",
        f"Departure: {offer.departure_at}",
        f"Duration: {offer.duration}  |  {stops_text}",
        f"Airline: {offer.airline}",
        "",
        f"Price: *{offer.currency} {offer.price:,.0f}*",
    ]

    if alert_type == "price_drop" and prev_price is not None:
        drop_pct = (prev_price - offer.price) / prev_price * 100
        lines.append(
            f"Price drop: {drop_pct:.1f}% (was {offer.currency} {prev_price:,.0f})"
        )
    elif alert_type == "below_threshold":
        lines.append("This flight is at or below your target price threshold.")

    if offer.max_layover_hours > 0:
        lines.append(f"Max layover: {offer.max_layover_hours:.1f}h")

    return "\n".join(lines)
