"""Utilidades de texto: normalizar, parsear importes, superficies y fechas."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

_WS = re.compile(r"\s+")


def clean(text: str | None) -> str:
    """Colapsa espacios y quita blancos de los extremos."""
    return _WS.sub(" ", text or "").strip()


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def norm(text: str | None) -> str:
    """Minúsculas, sin acentos y con espacios colapsados (para comparar)."""
    return clean(strip_accents(text or "").lower())


def slugify(text: str) -> str:
    """'Santa Cruz de Tenerife' -> 'santa-cruz-de-tenerife'."""
    t = norm(text).replace("/", " ").replace("'", "")
    t = re.sub(r"[^a-z0-9]+", "-", t)
    return t.strip("-")


_EURO_ES = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?")


def parse_euros(value) -> float | None:
    """Convierte importes en formato español a float.

    '36.060,73 €' -> 36060.73 ; '150.000€' -> 150000.0 ; 'Sin puja mínima' -> None.
    Acepta también números ya convertidos.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = clean(str(value))
    if not text or norm(text).startswith("sin") or "ver valor" in norm(text):
        return None
    text = text.replace("\xa0", " ").replace(" ", "")
    m = _EURO_ES.search(text)
    if not m:
        return None
    entero = m.group(1).replace(".", "")
    dec = m.group(2) or "0"
    try:
        return float(f"{entero}.{dec}")
    except ValueError:
        return None


_NUM_WORDS_M2 = re.compile(
    r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?\s*(?:m2|m\.?\s?2|m²|mts?\.?\s*2?|metros?\s*cuadrados?)",
    re.IGNORECASE,
)
_HECTAREAS = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?\s*(?:hect[aá]reas?|ha\b)", re.IGNORECASE)


def _to_float(entero: str, dec: str | None) -> float:
    return float(f"{entero.replace('.', '')}.{dec or '0'}")


def parse_m2(text: str | None) -> float | None:
    """Saca una superficie en m² de un texto libre.

    Si hay varias cifras (útil, construida...) devuelve la mayor plausible,
    que suele ser la construida. Las hectáreas se convierten a m².
    """
    if not text:
        return None
    if isinstance(text, (int, float)):
        return float(text) if text > 0 else None
    t = str(text).replace("\xa0", " ")
    vals = []
    for m in _NUM_WORDS_M2.finditer(t):
        try:
            v = _to_float(m.group(1), m.group(2))
        except ValueError:
            continue
        if 5 <= v <= 5_000_000:
            vals.append(v)
    if vals:
        return max(vals)
    mh = _HECTAREAS.search(t)
    if mh:
        try:
            return round(_to_float(mh.group(1), mh.group(2)) * 10_000, 1)
        except ValueError:
            return None
    return None


_ROOMS = re.compile(r"(\d+)\s*(?:hab\b|hab\.|habitaci[oó]n|habitaciones|dormitorios?|dorm\.)", re.IGNORECASE)
_BATHS = re.compile(r"(\d+)\s*(?:baños?|banos?|aseos?)", re.IGNORECASE)


def parse_rooms(text: str | None) -> int | None:
    if not text:
        return None
    m = _ROOMS.search(str(text))
    return int(m.group(1)) if m else None


def parse_baths(text: str | None) -> int | None:
    if not text:
        return None
    m = _BATHS.search(str(text))
    return int(m.group(1)) if m else None


_ISO_IN_TEXT = re.compile(r"ISO:\s*([0-9T:\-+]+)")
_DMY = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})(?:\D+(\d{1,2}):(\d{2})(?::(\d{2}))?)?")


def parse_date(text: str | None) -> str:
    """Devuelve la fecha en ISO 8601 (o '' si no se reconoce).

    Soporta '29-09-2026 18:00:00 CET (ISO: 2026-09-29T18:00:00+02:00)',
    '29/09/2026 10:30', '29/09/2026' y fechas ISO.
    """
    if not text:
        return ""
    t = clean(str(text))
    m = _ISO_IN_TEXT.search(t)
    if m:
        return m.group(1)
    m = _DMY.search(t)
    if m:
        d, mo, y, hh, mm, ss = m.groups()
        try:
            dt = datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0), int(ss or 0))
        except ValueError:
            return ""
        return dt.isoformat() if hh else dt.date().isoformat()
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return ""


_CATASTRO = re.compile(r"\b(\d{7})\s?([A-Z]{2}\d{4}[A-Z])(?:\s?(\d{4})\s?([A-Z]{2}))?\b")
_CATASTRO_RUSTICA = re.compile(r"\b(\d{5}[A-Z]\d{8})(?:\s?(\d{4})\s?([A-Z]{2}))?\b")


def find_cadastral_ref(text: str | None) -> str:
    """Busca una referencia catastral (14 o 20 caracteres) dentro de un texto."""
    if not text:
        return ""
    t = str(text).upper()
    m = _CATASTRO.search(t) or _CATASTRO_RUSTICA.search(t)
    return "".join(g for g in m.groups() if g) if m else ""
