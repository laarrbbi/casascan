"""Extracción genérica de anuncios de cualquier web inmobiliaria.

Las webs cambian a menudo su HTML, así que en vez de depender solo de selectores
CSS se prueban tres estrategias y se combinan:

1. JSON-LD (schema.org) que muchas webs incluyen para Google.
2. JSON incrustado en la página (__NEXT_DATA__, window.__INITIAL_STATE__...):
   se buscan objetos que "parecen" un anuncio (tienen precio + id/url).
3. Tarjetas HTML: enlaces a fichas cuyo contenedor muestra un precio en €.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..textutil import clean, norm, parse_baths, parse_euros, parse_m2, parse_rooms

PRICE_KEYS = ("price", "precio", "saleprice", "pricevalue", "rawprice", "importe", "precioventa",
              "precio_venta", "currentprice", "finalprice", "amount")
ID_KEYS = ("propertyid", "propertycode", "adid", "id", "reference", "referencia", "ref", "code", "codigo")
URL_KEYS = ("url", "detailurl", "link", "href", "permalink", "canonical", "uri", "detail", "slug")
SURFACE_KEYS = ("surface", "superficie", "size", "builtarea", "constructedarea", "area", "usablearea",
                "m2", "metros", "floorsize", "sqm", "surfacearea", "superficieconstruida")
ROOM_KEYS = ("rooms", "bedrooms", "habitaciones", "dormitorios", "numrooms", "roomnumber", "numberofrooms",
             "numberofbedrooms")
BATH_KEYS = ("bathrooms", "banos", "baños", "numbathrooms", "bathnumber", "numberofbathroomstotal")
TITLE_KEYS = ("title", "titulo", "name", "headline")
DESC_KEYS = ("description", "descripcion", "comments", "comment", "texto")
ADDRESS_KEYS = ("streetaddress", "address", "direccion", "street", "calle", "ubication", "addresstext")
CITY_KEYS = ("city", "municipality", "municipio", "localidad", "town", "addresslocality", "poblacion")
PROVINCE_KEYS = ("province", "provincia", "addressregion", "region")
ZIP_KEYS = ("postalcode", "zipcode", "codigopostal", "cp", "zip")
LAT_KEYS = ("latitude", "lat")
LON_KEYS = ("longitude", "lng", "lon")
TYPE_KEYS = ("propertytype", "tipo", "typology", "subtype", "tipologia", "@type")

_PRICE_IN_TEXT = re.compile(r"(\d{1,3}(?:[.\s]\d{3})+|\d{4,})\s*(?:€|eur\b|euros)", re.IGNORECASE)


# ---------------------------------------------------------------- helpers
def _num(value: Any) -> float | None:
    if isinstance(value, dict):
        for k in ("amount", "value", "price", "raw", "min"):
            if k in value:
                return _num(value[k])
        return None
    if isinstance(value, list) and value:
        return _num(value[0])
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        v = value.strip()
        if re.fullmatch(r"\d+(\.\d+)?", v):
            return float(v)
        return parse_euros(v)
    return None


def _flatten(obj: dict, depth: int = 0, out: dict | None = None) -> dict:
    """Aplana un objeto (2 niveles) a {clave_en_minúsculas: valor}.

    Las claves del nivel superior tienen prioridad sobre las de objetos anidados.
    """
    out = {} if out is None else out
    nested: list[tuple[str, Any]] = []
    for k, v in obj.items():
        lk = "@type" if k == "@type" else str(k).lower().replace("-", "").replace("_", "")
        if isinstance(v, (dict, list)):
            nested.append((lk, v))
        else:
            out.setdefault(lk, v)
    for lk, v in nested:
        if isinstance(v, dict) and depth < 2:
            _flatten(v, depth + 1, out)
        elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v) and depth < 2:
            # características tipo [{"key": "rooms", "value": 3}]
            for x in v:
                key = x.get("key") or x.get("name") or x.get("id")
                if isinstance(key, str) and "value" in x and not isinstance(x["value"], (dict, list)):
                    out.setdefault(key.lower().replace("_", ""), x["value"])
        out.setdefault(lk, v)
    return out


def _pick(flat: dict, keys: tuple[str, ...]) -> Any:
    for k in keys:
        k2 = k.replace("_", "")
        if k2 in flat and flat[k2] not in (None, "", [], {}):
            return flat[k2]
    return None


def _str(value: Any) -> str:
    if value is None or isinstance(value, (dict, list)):
        if isinstance(value, dict):
            parts = [str(v) for v in value.values() if isinstance(v, (str, int)) and str(v).strip()]
            return clean(", ".join(parts))
        return ""
    return clean(str(value))


def listing_from_object(obj: dict, base_url: str) -> dict | None:
    """Convierte un objeto JSON con pinta de anuncio en un dict normalizado."""
    flat = _flatten(obj)
    price = None
    for k in PRICE_KEYS:
        k = k.replace("_", "")
        if k in flat:
            price = _num(flat[k])
            if price:
                break
    if not price or price < 1000:  # descarta precios de alquiler/filtros raros
        return None
    url = _pick(flat, URL_KEYS)
    if isinstance(url, dict):
        url = next((v for v in url.values() if isinstance(v, str) and "/" in v), None)
    url = url if isinstance(url, str) and ("/" in url) else None
    ident = _pick(flat, ID_KEYS)
    if not url and ident in (None, ""):
        return None
    if url:
        url = urljoin(base_url, url)
    surface = _pick(flat, SURFACE_KEYS)
    rooms = _pick(flat, ROOM_KEYS)
    baths = _pick(flat, BATH_KEYS)
    title = _str(_pick(flat, TITLE_KEYS))
    desc = _str(_pick(flat, DESC_KEYS))
    lat, lon = _num(_pick(flat, LAT_KEYS)), _num(_pick(flat, LON_KEYS))
    return {
        "id": _str(ident) if ident is not None else "",
        "url": url or "",
        "title": title,
        "price": price,
        "surface_m2": _num(surface) if surface is not None else parse_m2(f"{title} {desc}"),
        "rooms": int(_num(rooms)) if _num(rooms) else parse_rooms(f"{title} {desc}"),
        "bathrooms": int(_num(baths)) if _num(baths) else parse_baths(f"{title} {desc}"),
        "address": _str(_pick(flat, ADDRESS_KEYS)),
        "city": _str(_pick(flat, CITY_KEYS)),
        "province": _str(_pick(flat, PROVINCE_KEYS)),
        "postal_code": _str(_pick(flat, ZIP_KEYS)),
        "description": desc,
        "property_type": _str(_pick(flat, TYPE_KEYS)),
        "lat": lat if lat and -90 <= lat <= 90 else None,
        "lon": lon if lon and -180 <= lon <= 180 else None,
    }


def walk_json(data: Any, base_url: str, out: list[dict], depth: int = 0) -> None:
    """Recorre un JSON y guarda todo objeto que parezca un anuncio."""
    if depth > 40:
        return
    if isinstance(data, dict):
        found = listing_from_object(data, base_url) if _looks_like_listing(data) else None
        if found:
            out.append(found)
            return
        for v in data.values():
            walk_json(v, base_url, out, depth + 1)
    elif isinstance(data, list):
        for v in data:
            walk_json(v, base_url, out, depth + 1)


def _looks_like_listing(d: dict) -> bool:
    keys = {str(k).lower().replace("_", "") for k in d}
    has_price = bool(keys & set(PRICE_KEYS)) or "offers" in keys or "transactions" in keys or "priceinfo" in keys
    has_ref = bool(keys & set(ID_KEYS)) or bool(keys & set(URL_KEYS))
    has_feature = bool(keys & set(SURFACE_KEYS + ROOM_KEYS + ADDRESS_KEYS + TITLE_KEYS + DESC_KEYS)) or (
        "features" in keys or "location" in keys or "geo" in keys
    )
    return has_price and has_ref and has_feature


# ------------------------------------------------------------- strategies
def from_json_ld(soup: BeautifulSoup, base_url: str) -> list[dict]:
    out: list[dict] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        walk_json(data, base_url, out)
    return out


_ASSIGN = re.compile(r"(?:window\.)?__[A-Za-z0-9_]+__\s*=\s*")
_JSON_PARSE = re.compile(r"JSON\.parse\(\s*([\"'])(.*?)(?<!\\)\1\s*\)", re.DOTALL)


def _js_payloads(text: str) -> list[Any]:
    """JSON asignado a variables globales: window.__X__ = {...} o = JSON.parse("...")."""
    payloads: list[Any] = []
    decoder = json.JSONDecoder()
    for m in _ASSIGN.finditer(text):
        rest = text[m.end():]
        try:
            if rest.startswith("JSON.parse"):
                pm = _JSON_PARSE.match(rest)
                if pm:
                    payloads.append(json.loads(json.loads(f'"{pm.group(2)}"')))
            elif rest[:1] in "{[":
                obj, _ = decoder.raw_decode(rest)
                payloads.append(obj)
        except (json.JSONDecodeError, ValueError):
            continue
    return payloads


def from_embedded_json(soup: BeautifulSoup, base_url: str) -> list[dict]:
    out: list[dict] = []
    for script in soup.find_all("script"):
        stype = (script.get("type") or "").lower()
        text = script.string or script.get_text() or ""
        if not text or stype == "application/ld+json":
            continue
        payloads: list[Any] = []
        if stype == "application/json" or script.get("id") == "__NEXT_DATA__":
            try:
                payloads.append(json.loads(text))
            except json.JSONDecodeError:
                pass
        elif "__" in text and "=" in text:
            payloads.extend(_js_payloads(text))
        for p in payloads:
            walk_json(p, base_url, out)
    return out


def from_cards(soup: BeautifulSoup, base_url: str, detail_pattern: str | None = None) -> list[dict]:
    host = urlparse(base_url).netloc
    pattern = re.compile(detail_pattern) if detail_pattern else None
    out: list[dict] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"].split("#")[0])
        if href in seen or urlparse(href).netloc not in ("", host):
            continue
        if pattern:
            if not pattern.search(href):
                continue
        elif not re.search(r"\d{5,}", urlparse(href).path):
            continue
        card = a
        for _ in range(7):
            if card.parent is None:
                break
            card = card.parent
            text = card.get_text(" ")
            if _PRICE_IN_TEXT.search(text):
                break
        else:
            continue
        text = clean(card.get_text(" "))
        m = _PRICE_IN_TEXT.search(text)
        if not m or len(text) > 3000:
            continue
        seen.add(href)
        heading = card.find(["h2", "h3", "h4"])
        title = clean((heading or a).get_text(" ")) or clean(a.get("title", ""))
        ident = re.findall(r"\d{5,}", urlparse(href).path)
        out.append(
            {
                "id": ident[-1] if ident else href,
                "url": href,
                "title": title[:200],
                "price": parse_euros(m.group(1).replace(" ", ".")),
                "surface_m2": parse_m2(text),
                "rooms": parse_rooms(text),
                "bathrooms": parse_baths(text),
                "address": "",
                "city": "",
                "province": "",
                "postal_code": "",
                "description": text[:500],
                "property_type": "",
                "lat": None,
                "lon": None,
            }
        )
    return out


def extract_listings(html: str, base_url: str, detail_pattern: str | None = None) -> list[dict]:
    """Combina las tres estrategias y deduplica por url / id."""
    soup = BeautifulSoup(html, "lxml")
    results: list[dict] = []
    for strategy in (from_json_ld, from_embedded_json):
        results.extend(strategy(soup, base_url))
    results.extend(from_cards(soup, base_url, detail_pattern))
    merged: dict[str, dict] = {}
    for r in results:
        key = r["url"] or f"id:{r['id']}"
        if key in merged:
            for k, v in r.items():
                if merged[key].get(k) in (None, "") and v not in (None, ""):
                    merged[key][k] = v
            continue
        # misma ficha encontrada por id con y sin url
        dup = next((m for m in merged.values() if r["id"] and m["id"] == r["id"]), None)
        if dup:
            for k, v in r.items():
                if dup.get(k) in (None, "") and v not in (None, ""):
                    dup[k] = v
            continue
        merged[key] = dict(r)
    return list(merged.values())


def discover_links(html: str, base_url: str, must_contain: list[str], any_of: list[str] = ()) -> list[str]:
    """Enlaces de la página cuyo href contiene todos los textos `must_contain`
    (y al menos uno de `any_of`). Sirve para encontrar la URL de una provincia."""
    soup = BeautifulSoup(html, "lxml")
    found: list[str] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        h = norm(href)
        if all(norm(x) in h for x in must_contain) and (not any_of or any(norm(x) in h for x in any_of)):
            found.append(href)
    return list(dict.fromkeys(found))
