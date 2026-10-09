"""Avisos por Telegram de los resultados nuevos y las bajadas de precio.

Configuración: crea un bot con @BotFather, guarda el token en TELEGRAM_TOKEN y
tu chat id en TELEGRAM_CHAT_ID (o ponlos en config.yaml).
"""

from __future__ import annotations

import html
import logging

import requests

from .models import Listing
from .report import SOURCE_LABELS

log = logging.getLogger("casascan.notify")
MAX_LEN = 3900  # Telegram admite 4096 caracteres por mensaje


def _eur(v) -> str:
    return f"{v:,.0f} €".replace(",", ".") if v else "—"


def format_item(it: Listing) -> str:
    head = "🆕" if it.is_new else "📉"
    parts = [f"{head} <b>{html.escape(SOURCE_LABELS.get(it.source, it.source))}</b> · {_eur(it.price)}"]
    if it.price_drop:
        parts[0] += f" (antes {_eur(it.previous_price)})"
    details = " · ".join(
        x for x in (
            f"{it.surface_m2:.0f} m²" if it.surface_m2 else "",
            f"{it.rooms} hab." if it.rooms else "",
            ", ".join(y for y in (it.city, it.province) if y),
            f"fin {it.end_date[:10]}" if it.end_date else "",
        ) if x
    )
    parts.append(html.escape((it.title or it.address or it.id)[:140]))
    if details:
        parts.append(html.escape(details))
    parts.append(f'<a href="{html.escape(it.url)}">abrir</a>')
    return "\n".join(parts)


def send_telegram(items: list[Listing], token: str, chat_id: str) -> int:
    """Envía los resultados (agrupados en mensajes) y devuelve cuántos mensajes salieron."""
    if not token or not chat_id or not items:
        return 0
    blocks = [format_item(it) for it in items]
    messages, current = [], f"<b>CasaScan</b>: {len(items)} novedades\n"
    for b in blocks:
        if len(current) + len(b) + 2 > MAX_LEN:
            messages.append(current)
            current = ""
        current += "\n" + b + "\n"
    messages.append(current)
    return sum(1 for msg in messages if send_text(msg, token, chat_id))


def send_text(text: str, token: str, chat_id: str) -> bool:
    """Envía un mensaje (HTML de Telegram). Devuelve True si se entregó."""
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"},
            timeout=30,
        )
    except requests.RequestException as exc:
        log.warning("No se pudo enviar a Telegram: %s", exc)
        return False
    if not r.ok:
        log.warning("Telegram respondió %s: %s", r.status_code, r.text[:200])
    return r.ok
