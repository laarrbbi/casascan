"""Idealista.

Dos modos:
- **API oficial** (recomendado): si defines IDEALISTA_API_KEY e IDEALISTA_API_SECRET
  (se piden gratis en https://developers.idealista.com/access-request).
  Permite filtrar por "pisos de bancos" (bankOffer) y no hay captchas.
- **HTML**: lee las páginas de resultados de idealista.com. Idealista usa un
  anti-bot (DataDome) muy agresivo: con `requests` suele devolver captcha, así que
  en este modo conviene usar `--navegador` (Chromium real con Playwright).
  También puedes pegar en config.yaml tus propias URLs de búsqueda (con los
  filtros hechos en la web), por ejemplo las de bancos/Sareb:
  https://www.idealista.com/pro/aliseda/venta-viviendas/
"""

from __future__ import annotations

import base64
import os
import re
from collections.abc import Iterator
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..models import VENTA, Listing
from ..provinces import province_code, province_name, province_slug
from ..textutil import clean, norm, parse_baths, parse_euros, parse_m2, parse_rooms
from .base import Source

WEB = "https://www.idealista.com"
TOKEN_URL = "https://api.idealista.com/oauth/token"
API_SEARCH_URL = "https://api.idealista.com/3.5/es/search"

# Slug de provincia en idealista: "<provincia>-provincia" salvo cuando la capital
# se llama distinto (entonces el slug de la provincia va sin sufijo).
_SLUG_OVERRIDES = {
    "01": "alava", "03": "alicante", "07": "balears-illes", "12": "castellon",
    "20": "gipuzkoa", "26": "la-rioja", "31": "navarra", "33": "asturias",
    "35": "las-palmas", "39": "cantabria", "48": "bizkaia", "51": "ceuta", "52": "melilla",
}
WEB_TYPE_PATH = {
    "vivienda": "venta-viviendas", "local": "venta-locales", "garaje": "venta-garajes",
    "trastero": "venta-trasteros", "nave": "venta-naves", "solar": "venta-terrenos",
    "rustica": "venta-terrenos", "edificio": "venta-edificios",
}
API_TYPE = {"vivienda": "homes", "local": "premises", "garaje": "garages", "nave": "premises"}
_API_TYPE_BACK = {
    "flat": "vivienda", "chalet": "vivienda", "duplex": "vivienda", "penthouse": "vivienda",
    "studio": "vivienda", "countryhouse": "vivienda", "homes": "vivienda", "garage": "garaje",
    "garages": "garaje", "premise": "local", "premises": "local", "office": "local",
}


def idealista_province_slug(code: str) -> str:
    return _SLUG_OVERRIDES.get(code) or f"{province_slug(code)}-provincia"


def build_web_url(code: str, ptype: str, criteria: dict) -> str:
    path = WEB_TYPE_PATH.get(ptype, "venta-viviendas")
    url = f"{WEB}/{path}/{idealista_province_slug(code)}/"
    if criteria.get("precio_max"):
        url += f"con-precio-hasta_{int(criteria['precio_max'])}/"
    return url + "?ordenado-por=fecha-publicacion-desc"


def page_url(url: str, page: int) -> str:
    """Página N de una búsqueda: .../pagina-N.htm (conservando la query)."""
    if page <= 1:
        return url
    parts = urlsplit(url)
    path = re.sub(r"pagina-\d+\.htm$", "", parts.path)
    if not path.endswith("/"):
        path += "/"
    return urlunsplit((parts.scheme, parts.netloc, f"{path}pagina-{page}.htm", parts.query, ""))


def parse_search_page(html: str) -> tuple[list[dict], bool]:
    """Anuncios de una página de resultados de idealista + si hay página siguiente."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for art in soup.select("article.item, article[data-element-id], article[data-adid]"):
        link = art.select_one("a.item-link") or art.find("a", href=re.compile(r"/inmueble/\d+"))
        if not link:
            continue
        href = urljoin(WEB, link.get("href", ""))
        m = re.search(r"/inmueble/(\d+)", href)
        ident = art.get("data-element-id") or art.get("data-adid") or (m.group(1) if m else href)
        price_el = art.select_one(".item-price, .price-row .item-price")
        details = [clean(s.get_text(" ")) for s in art.select(".item-detail, .item-detail-char span")]
        details_txt = " · ".join(dict.fromkeys(d for d in details if d))
        desc_el = art.select_one(".item-description, .ellipsis")
        title = clean(link.get("title") or link.get_text(" "))
        logo = art.select_one(".logo-branding img")
        out.append(
            {
                "id": str(ident),
                "url": href,
                "title": title,
                "price": parse_euros(price_el.get_text(" ") if price_el else ""),
                "surface_m2": parse_m2(details_txt),
                "rooms": parse_rooms(details_txt),
                "bathrooms": parse_baths(details_txt),
                "details": details_txt,
                "description": clean(desc_el.get_text(" ")) if desc_el else "",
                "seller": clean(logo.get("alt", "")) if logo else "",
            }
        )
    has_next = bool(soup.select_one(".pagination li.next a, a.icon-arrow-right-after"))
    return out, has_next


def city_from_title(title: str) -> str:
    """'Piso en calle Mayor, Centro, Madrid' -> 'Madrid'."""
    parts = [p.strip() for p in title.split(",") if p.strip()]
    return parts[-1] if len(parts) >= 2 else ""


class IdealistaSource(Source):
    name = "idealista"
    label = "Idealista"
    homepage = WEB

    def search(self, provinces: list[str]) -> Iterator[Listing]:
        key, secret = os.environ.get("IDEALISTA_API_KEY"), os.environ.get("IDEALISTA_API_SECRET")
        urls = self.opt("urls", []) or []
        if urls:
            yield from self._search_urls([(u, "") for u in urls])
        elif key and secret:
            yield from self._search_api(provinces, key, secret)
        else:
            paths: dict[str, str] = {}  # una búsqueda por ruta (solar y rústica comparten)
            for t in self.wanted_types or ["vivienda"]:
                if t in WEB_TYPE_PATH:
                    paths.setdefault(WEB_TYPE_PATH[t], t)
            pairs = [(build_web_url(prov, t, self.criteria), prov) for prov in provinces for t in paths.values()]
            yield from self._search_urls(pairs)

    # ---------------------------------------------------------------- HTML
    def _search_urls(self, pairs: list[tuple[str, str]]) -> Iterator[Listing]:
        max_pages = int(self.opt("max_paginas", 3))
        for base, prov in pairs:
            for page in range(1, max_pages + 1):
                url = page_url(base, page)
                html = self.http.get_html(url, impersonate=True, wait_selector="article.item")
                items, has_next = parse_search_page(html)
                self.log.info("%s → %d anuncios", url, len(items))
                for it in items:
                    yield self._from_web(it, prov)
                if not items or not has_next:
                    break

    def _from_web(self, it: dict, prov: str) -> Listing:
        city = city_from_title(it["title"])
        ptype = ""
        t = norm(it["title"])
        if any(w in t for w in ("piso", "casa", "chalet", "atico", "duplex", "estudio", "apartamento")):
            ptype = "vivienda"
        elif "local" in t:
            ptype = "local"
        elif "garaje" in t or "plaza" in t:
            ptype = "garaje"
        return Listing(
            source=self.name,
            id=it["id"],
            url=it["url"],
            title=it["title"],
            kind=VENTA,
            property_type=ptype,
            price=it["price"],
            surface_m2=it["surface_m2"],
            rooms=it["rooms"],
            bathrooms=it["bathrooms"],
            address=it["title"],
            city=city,
            province=province_name(prov) if prov else "",
            province_code=prov,
            description=it["description"],
            seller=it.get("seller", ""),
            extra={"detalles": it.get("details", "")},
        )

    # ----------------------------------------------------------------- API
    def _token(self, key: str, secret: str) -> str:
        auth = base64.b64encode(f"{key}:{secret}".encode()).decode()
        r = self.http.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials", "scope": "read"},
            headers={"Authorization": f"Basic {auth}",
                     "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        )
        if r.status != 200:
            raise RuntimeError(f"Idealista API: no se pudo obtener token (HTTP {r.status}): {r.text[:200]}")
        return r.json()["access_token"]

    def _search_api(self, provinces: list[str], key: str, secret: str) -> Iterator[Listing]:
        token = self._token(key, secret)
        c = self.criteria
        types = [API_TYPE[t] for t in (self.wanted_types or ["vivienda"]) if t in API_TYPE]
        for prov in provinces:
            for ptype in dict.fromkeys(types or ["homes"]):
                for page in range(1, int(self.opt("max_paginas", 3)) + 1):
                    params = {
                        "operation": "sale",
                        "propertyType": ptype,
                        "locationId": f"0-EU-ES-{prov}",
                        "maxItems": 50,
                        "numPage": page,
                        "order": "publicationDate",
                        "sort": "desc",
                        "language": "es",
                    }
                    if c.get("precio_max"):
                        params["maxPrice"] = int(c["precio_max"])
                    if c.get("precio_min"):
                        params["minPrice"] = int(c["precio_min"])
                    if c.get("superficie_min"):
                        params["minSize"] = int(c["superficie_min"])
                    if c.get("superficie_max"):
                        params["maxSize"] = int(c["superficie_max"])
                    if ptype == "homes" and c.get("habitaciones_min"):
                        n = int(c["habitaciones_min"])
                        params["bedrooms"] = ",".join(str(i) for i in range(n, 5))
                    if self.opt("solo_bancos", False):
                        params["bankOffer"] = "true"
                    r = self.http.post(API_SEARCH_URL, data=params,
                                       headers={"Authorization": f"Bearer {token}"})
                    data = r.json()
                    elements = data.get("elementList", [])
                    self.log.info("%s (%s) pág. %d: %d anuncios", province_name(prov), ptype, page, len(elements))
                    for e in elements:
                        yield self._from_api(e, prov)
                    if page >= int(data.get("totalPages", 0) or 0) or not elements:
                        break

    def _from_api(self, e: dict, prov: str) -> Listing:
        ptype = _API_TYPE_BACK.get(norm(str(e.get("propertyType", ""))).replace(" ", ""), "")
        title = (e.get("suggestedTexts") or {}).get("title") or e.get("address") or ""
        return Listing(
            source=self.name,
            id=str(e.get("propertyCode")),
            url=e.get("url") or f"{WEB}/inmueble/{e.get('propertyCode')}/",
            title=title,
            kind=VENTA,
            property_type=ptype,
            price=e.get("price"),
            surface_m2=e.get("size"),
            rooms=e.get("rooms"),
            bathrooms=e.get("bathrooms"),
            address=e.get("address", ""),
            city=e.get("municipality", ""),
            province=e.get("province") or province_name(prov),
            province_code=province_code(e.get("province")) or prov,
            description=e.get("description", ""),
            lat=e.get("latitude"),
            lon=e.get("longitude"),
            extra={
                "planta": e.get("floor"),
                "estado": e.get("status"),
                "ascensor": e.get("hasLift"),
                "exterior": e.get("exterior"),
                "distrito": e.get("district"),
                "barrio": e.get("neighborhood"),
            },
        )
