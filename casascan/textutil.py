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


# --------------------------------------------------------------------------
# Números escritos en letra: en las fichas de subastas los juzgados y notarías
# escriben "ochenta y cinco metros y cincuenta decímetros cuadrados" o "tres
# dormitorios", así que hay que entender los números en castellano.
_WORD_VALUES: dict[str, int] = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12,
    "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17,
    "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiun": 21, "veintiuno": 21,
    "veintiuna": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24,
    "veinticinco": 25, "veintiseis": 26, "veintisiete": 27, "veintiocho": 28,
    "veintinueve": 29, "veintinuevo": 29, "treinta": 30, "cuarenta": 40, "cincuenta": 50,
    "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90, "cien": 100, "ciento": 100,
    "doscientos": 200, "doscientas": 200, "trescientos": 300, "trescientas": 300,
    "cuatrocientos": 400, "cuatrocientas": 400, "quinientos": 500, "quinientas": 500,
    "seiscientos": 600, "seiscientas": 600, "setecientos": 700, "setecientas": 700,
    "ochocientos": 800, "ochocientas": 800, "novecientos": 900, "novecientas": 900,
}
_TOKEN = re.compile(r"\d+(?:[.,]\d+)*|[a-z]+")

# Palabras que, justo antes de "X metros", indican que es una superficie
_AREA_HINTS = ("superficie", "extension", "ocupa", "mide", "cabida", "construid", "util", "edificad",
               "solar de", "parcela de", "terreno de")
# ... y las que justo después indican que es una medida lineal
_LINEAR_AFTER = ("de frente", "de fondo", "lineal", "de altura", "de longitud", "de ancho", "de largo",
                 "de distancia")


def _digits_value(tok: str) -> float | None:
    """'1.250,50' -> 1250.5 ; '85,50' -> 85.5 ; '1.250' -> 1250 ; '85.5' -> 85.5"""
    try:
        if "," in tok:
            return float(tok.replace(".", "").replace(",", "."))
        if "." in tok:
            parts = tok.split(".")
            if all(len(p) == 3 for p in parts[1:]):
                return float(tok.replace(".", ""))
            return float(tok)
        return float(tok)
    except ValueError:
        return None


def _number_at(tokens: list[tuple[str, int, int]], i: int) -> tuple[float | None, int]:
    """Lee un número (en cifras o en letra) que empieza en tokens[i].

    Devuelve (valor, índice del primer token tras el número) o (None, i).
    """
    tok = tokens[i][0]
    if tok[0].isdigit():
        return _digits_value(tok), i + 1
    total = current = 0
    j, seen = i, False
    while j < len(tokens):
        w = tokens[j][0]
        if w == "y" and seen and j + 1 < len(tokens) and tokens[j + 1][0] in _WORD_VALUES:
            j += 1
            continue
        if w == "mil" and (seen or j == i):
            total += (current or 1) * 1000
            current, seen = 0, True
            j += 1
            continue
        if w not in _WORD_VALUES:
            break
        current += _WORD_VALUES[w]
        seen = True
        j += 1
    return (float(total + current), j) if seen else (None, i)


def _numbers_before(text: str, units: tuple[str, ...]):
    """Recorre el texto normalizado y devuelve (valor, inicio, fin_unidad, unidad) de
    cada número seguido de una de las unidades indicadas (prefijos)."""
    t = norm(text)
    tokens = [(m.group(), m.start(), m.end()) for m in _TOKEN.finditer(t)]
    i = 0
    while i < len(tokens):
        value, j = _number_at(tokens, i)
        if value is None:
            i += 1
            continue
        if j < len(tokens):
            unit = tokens[j][0]
            for u in units:
                if unit.startswith(u):
                    yield t, value, tokens[i][1], j, tokens, u
                    break
        i = max(j, i + 1)


def parse_m2(text: str | None) -> float | None:
    """Saca la superficie en m² de un texto libre (cifras o letra).

    Entiende '85,50 m²', 'ochenta y cinco metros y cincuenta decímetros
    cuadrados', 'una superficie de treinta y cinco metros' y hectáreas. Si hay
    varias superficies, prefiere la construida; si no, la mayor.
    """
    if not text:
        return None
    if isinstance(text, (int, float)):
        return float(text) if text > 0 else None
    candidates: list[tuple[float, bool]] = []  # (valor, es_construida)
    for t, value, start, j, tokens, unit in _numbers_before(str(text), ("m", "hect", "ha")):
        tok = tokens[j][0]
        nxt = tokens[j + 1][0] if j + 1 < len(tokens) else ""
        before = t[max(0, start - 70):start]
        after = t[tokens[j][2]:tokens[j][2] + 90].split(". ")[0]
        if unit in ("hect", "ha"):
            if tok in ("ha", "hectarea", "hectareas"):
                candidates.append((value * 10_000, False))
            continue
        if tok == "m2" or (tok in ("m", "mts", "mt", "mtrs") and nxt == "2") or tok in ("mts2", "mt2"):
            area = True
        elif tok in ("metro", "metros", "mts", "mtrs"):
            area = "cuadrad" in after or (
                any(h in before[-45:] for h in _AREA_HINTS)
                and not any(after.lstrip(" ,").startswith(x) for x in _LINEAR_AFTER)
            )
            if area and tok.startswith("metro"):
                # '... metros y treinta y cinco decímetros cuadrados'
                k = j + 1
                if k < len(tokens) and tokens[k][0] in ("y", "con"):
                    k += 1
                if k < len(tokens):
                    dec, k2 = _number_at(tokens, k)
                    if dec is not None and k2 < len(tokens) and tokens[k2][0].startswith(("decim", "deim", "dm")):
                        value += dec / 100
        else:
            area = False
        if area and 5 <= value <= 5_000_000:
            candidates.append((round(value, 2), "construid" in before[-60:]))
    if not candidates:
        return None
    built = [v for v, c in candidates if c]
    return max(built) if built else max(v for v, _ in candidates)


def _count_before(text: str | None, units: tuple[str, ...]) -> int | None:
    if not text:
        return None
    for _t, value, *_rest in _numbers_before(str(text), units):
        if value is not None and 0 < value < 30 and value == int(value):
            return int(value)
    return None


def parse_rooms(text: str | None) -> int | None:
    """Dormitorios/habitaciones: '3 hab.', 'tres dormitorios', '2 habitaciones'."""
    return _count_before(text, ("dormitorio", "dorm")) or _count_before(text, ("hab",))


def parse_baths(text: str | None) -> int | None:
    """Baños: '2 baños', 'un cuarto de baño', 'dos aseos'."""
    n = _count_before(text, ("bano", "aseo"))
    if n is None and text and re.search(r"\b(un|1)\s+cuartos?\s+de\s+ba", norm(text)):
        return 1
    return n


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
