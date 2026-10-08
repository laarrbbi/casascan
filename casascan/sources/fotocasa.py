"""Fotocasa.

1. API JSON interna que usa la propia web (más estable que el HTML):
     search.gw.fotocasa.es/v2/suggest  -> identificador de la provincia
     web.gw.fotocasa.es/v1/search/ads  -> anuncios paginados (30 por página)
2. Si la API falla o está bloqueada, se leen las páginas de resultados
   https://www.fotocasa.es/es/comprar/viviendas/<provincia>-provincia/todas-las-zonas/l
   con el extractor genérico (JSON incrustado + tarjetas).

Fotocasa tiene anti-bot: instalar `curl_cffi` (imita a Chrome) ayuda mucho; si
aun así bloquea, usa `--navegador`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from urllib.parse import urlencode

from ..http import BlockedError
from ..models import VENTA, Listing
from ..provinces import province_code, province_name, province_slug
from ..textutil import norm
from .base import Source
from .generic import _flatten, extract_listings, listing_from_object

WEB = "https://www.fotocasa.es"
SUGGEST_URL = "https://search.gw.fotocasa.es/v2/suggest"
ADS_URL = "https://web.gw.fotocasa.es/v1/search/ads"
API_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": WEB,
    "Referer": f"{WEB}/",
}
WEB_TYPE_PATH = {
    "vivienda": "viviendas", "local": "locales", "garaje": "garajes", "trastero": "trasteros",
    "nave": "naves-industriales", "solar": "terrenos", "rustica": "terrenos", "edificio": "edificios",
}


def build_web_url(code: str, ptype: str, criteria: dict, page: int = 1) -> str:
    path = WEB_TYPE_PATH.get(ptype, "viviendas")
    url = f"{WEB}/es/comprar/{path}/{province_slug(code)}-provincia/todas-las-zonas/l"
    if page > 1:
        url += f"/{page}"
    q = {}
    if criteria.get("precio_max"):
        q["maxPrice"] = int(criteria["precio_max"])
    if criteria.get("precio_min"):
        q["minPrice"] = int(criteria["precio_min"])
    if criteria.get("habitaciones_min"):
        q["minRooms"] = int(criteria["habitaciones_min"])
    if criteria.get("superficie_min"):
        q["minSurface"] = int(criteria["superficie_min"])
    return url + (f"?{urlencode(q)}" if q else "")


def pick_location(suggestions: list[dict], code: str) -> dict | None:
    """Elige la sugerencia que corresponde a la provincia completa."""
    if not suggestions:
        return None
    name = norm(province_name(code).split("/")[0])
    def score(s: dict) -> tuple:
        text = norm(f"{s.get('text', '')} {s.get('baseText', '')}")
        typ = norm(str(s.get("type", "")))
        return (
            "provincia" in text or "prov" in typ,
            name in text,
            s.get("adsCount") or 0,
        )
    return max(suggestions, key=score)


def listing_from_ad(ad: dict) -> dict:
    """Normaliza un anuncio de la API de Fotocasa (tolerante a cambios de formato)."""
    base = listing_from_object(ad, WEB) or {}
    flat = _flatten(ad)
    ident = str(ad.get("propertyId") or ad.get("id") or base.get("id") or "")
    url = base.get("url") or ""
    if not url or not url.startswith("http"):
        # Si la API no trae la URL se construye la de la ficha a partir del id.
        url = f"{WEB}/es/comprar/vivienda/x/x/{ident}/d" if ident else ""
    city = base.get("city") or str(flat.get("level5name") or flat.get("level4name") or "")
    province = base.get("province") or str(flat.get("level2name") or "")
    return {**base, "id": ident, "url": url, "city": city, "province": province}


class FotocasaSource(Source):
    name = "fotocasa"
    label = "Fotocasa"
    homepage = WEB

    def search(self, provinces: list[str]) -> Iterator[Listing]:
        urls = self.opt("urls", []) or []
        if urls:
            for url in urls:
                yield from self._web_pages(url, "")
            return
        types = self.wanted_types or ["vivienda"]
        for prov in provinces:
            if "vivienda" in types:
                try:
                    yield from self._api(prov)
                except (BlockedError, ConnectionError, ValueError, KeyError) as exc:
                    self.log.warning("API de Fotocasa no disponible (%s); se usa la web", exc)
                    yield from self._web(prov, "vivienda")
            paths: dict[str, str] = {}  # una búsqueda por ruta (solar y rústica comparten)
            for t in types:
                if t != "vivienda" and t in WEB_TYPE_PATH:
                    paths.setdefault(WEB_TYPE_PATH[t], t)
            for t in paths.values():
                yield from self._web(prov, t)

    # ----------------------------------------------------------------- API
    def _api(self, prov: str) -> Iterator[Listing]:
        name = province_name(prov).split("/")[0]
        sugg = self.http.post(
            SUGGEST_URL,
            json={"query": name, "filters": {"propertyTypeFilter": "HOME", "transactionTypeFilter": "SALE"}},
            headers=API_HEADERS,
            impersonate=True,
        ).json()
        loc = pick_location(sugg if isinstance(sugg, list) else sugg.get("items", []), prov)
        if not loc or not loc.get("combinedLocationIds"):
            raise ValueError(f"sin ubicación para {name}")
        coords = loc.get("coordinates") or {}
        for page in range(1, int(self.opt("max_paginas", 3)) + 1):
            payload = {
                "combinedLocations": [loc["combinedLocationIds"]],
                "contracts": [],
                "includePurchaseTypeFacets": True,
                "isMap": False,
                "latitude": coords.get("latitude"),
                "longitude": coords.get("longitude"),
                "pageNumber": page,
                "pageSize": 30,
                "size": 30,
                "propertyType": 2,      # viviendas
                "transactionType": 1,   # compra
                "sortOrderDesc": True,
                "sortType": "publicationDate",
                "isSuperTopVariant": False,
            }
            data = self.http.post(ADS_URL, json=payload, headers=API_HEADERS, impersonate=True).json()
            items = data.get("items") or data.get("realEstates") or []
            self.log.info("%s pág. %d: %d anuncios", name, page, len(items))
            for ad in items:
                d = listing_from_ad(ad)
                if d.get("id"):
                    yield self._to_listing(d, prov, "vivienda")
            if len(items) < 30:
                break

    # ---------------------------------------------------------------- HTML
    def _web(self, prov: str, ptype: str) -> Iterator[Listing]:
        yield from self._web_pages(build_web_url(prov, ptype, self.criteria), prov, ptype=ptype)

    def _web_pages(self, url: str, prov: str, ptype: str = "") -> Iterator[Listing]:
        for page in range(1, int(self.opt("max_paginas", 3)) + 1):
            page_url = url if page == 1 else re.sub(r"/l(/\d+)?(\?|$)", rf"/l/{page}\2", url, count=1)
            if page > 1 and page_url == url:  # URL sin paginación reconocible
                break
            html = self.http.get_html(page_url, impersonate=True, wait_selector="article")
            items = extract_listings(html, WEB, detail_pattern=r"/comprar/[^/]+/.+/\d+/d")
            self.log.info("%s → %d anuncios", page_url, len(items))
            for it in items:
                yield self._to_listing(it, prov, ptype)
            if not items:
                break

    def _to_listing(self, d: dict, prov: str, ptype: str) -> Listing:
        prov_code = province_code(d.get("province")) or prov
        return Listing(
            source=self.name,
            id=str(d.get("id") or d.get("url")),
            url=d.get("url") or WEB,
            title=d.get("title") or d.get("address") or "",
            kind=VENTA,
            property_type=ptype,
            price=d.get("price"),
            surface_m2=d.get("surface_m2"),
            rooms=d.get("rooms"),
            bathrooms=d.get("bathrooms"),
            address=d.get("address") or "",
            postal_code=d.get("postal_code") or "",
            city=d.get("city") or "",
            province=d.get("province") or (province_name(prov_code) if prov_code else ""),
            province_code=prov_code or "",
            description=d.get("description") or "",
            lat=d.get("lat"),
            lon=d.get("lon"),
        )
