"""Base para las webs de los 'servicers' que venden pisos de bancos y de la Sareb
(Aliseda, Servihabitat...).

Estas webs cambian de estructura a menudo, así que:
1. Si en config.yaml hay `urls`, se usan tal cual (lo más fiable: haz la
   búsqueda en la web con tus filtros y pega la URL).
2. Si no, se busca en la portada el enlace de cada provincia (descubrimiento).
3. Si tampoco, se prueban las plantillas de URL conocidas.
Los anuncios se extraen con el extractor genérico (JSON-LD, JSON incrustado y
tarjetas HTML), y se pagina con ?page=N.
"""

from __future__ import annotations

from collections.abc import Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..models import VENTA, Listing
from ..provinces import ccaa_slug, province_code, province_name, province_slugs
from ..textutil import norm
from .base import Source
from .boe import property_type_from_text
from .generic import discover_links, extract_listings


def with_page(url: str, page: int, param: str = "page") -> str:
    parts = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != param]
    if page > 1:
        q.append((param, str(page)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), ""))


class ServicerSource(Source):
    home_url: str = ""
    discovery_pages: tuple[str, ...] = ()
    link_hints: tuple[str, ...] = ()        # el enlace de provincia debe contener alguno
    url_templates: tuple[str, ...] = ()     # {ccaa} y {prov}
    detail_pattern: str | None = None
    page_param: str = "page"
    seller_name: str = ""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._discovery_html: dict[str, str] = {}
        self._errors: list[Exception] = []
        self._pages_ok = 0

    def search(self, provinces: list[str]) -> Iterator[Listing]:
        urls = self.opt("urls", []) or []
        if urls:
            for url in urls:
                yield from self._crawl(url, "")
        else:
            for prov in provinces:
                found = False
                for url in self.candidate_urls(prov):
                    listings = list(self._crawl(url, prov))
                    if listings:
                        found = True
                        yield from listings
                        break
                if not found:
                    self.log.warning(
                        "%s: no he encontrado anuncios para %s. Abre %s, busca la provincia y pega la "
                        "URL en config.yaml (fuentes.%s.urls).",
                        self.label, province_name(prov), self.home_url, self.name,
                    )
        if self._errors and not self._pages_ok:
            raise self._errors[-1]  # ninguna página se pudo abrir: que conste como error

    def candidate_urls(self, prov: str) -> list[str]:
        slugs = province_slugs(prov)
        out: list[str] = []
        for page in self.discovery_pages:
            if page not in self._discovery_html:
                try:
                    self._discovery_html[page] = self.http.get_html(page, impersonate=True)
                    self._pages_ok += 1
                except Exception as exc:
                    self.log.info("No se pudo abrir %s: %s", page, exc)
                    self._errors.append(exc)
                    self._discovery_html[page] = ""
            html = self._discovery_html[page]
            for slug in slugs:
                for link in discover_links(html, page, [], list(self.link_hints)):
                    path = norm(urlsplit(link).path).rstrip("/")
                    if path.endswith(f"/{slug}"):
                        out.append(link)
        for tpl in self.url_templates:
            for slug in slugs:
                out.append(tpl.format(ccaa=ccaa_slug(prov), prov=slug))
        return list(dict.fromkeys(out))

    def _crawl(self, url: str, prov: str) -> Iterator[Listing]:
        seen: set[str] = set()
        for page in range(1, int(self.opt("max_paginas", 5)) + 1):
            page_url = with_page(url, page, self.page_param)
            try:
                html = self.http.get_html(page_url, impersonate=True)
                self._pages_ok += 1
            except Exception as exc:
                self.log.info("%s: %s", page_url, exc)
                self._errors.append(exc)
                return
            items = extract_listings(html, page_url, self.detail_pattern)
            new = [it for it in items if (it["url"] or it["id"]) not in seen]
            self.log.info("%s → %d anuncios", page_url, len(new))
            if not new:
                return
            for it in new:
                seen.add(it["url"] or it["id"])
                yield self._to_listing(it, prov)

    def _to_listing(self, d: dict, prov: str) -> Listing:
        code = province_code(d.get("province")) or prov
        ptype = property_type_from_text(f"{d.get('property_type', '')} {d.get('title', '')}")
        return Listing(
            source=self.name,
            id=str(d.get("id") or d.get("url")),
            url=d.get("url") or self.home_url,
            title=d.get("title") or "",
            kind=VENTA,
            property_type=ptype,
            price=d.get("price"),
            surface_m2=d.get("surface_m2"),
            rooms=d.get("rooms"),
            bathrooms=d.get("bathrooms"),
            address=d.get("address") or "",
            postal_code=d.get("postal_code") or "",
            city=d.get("city") or "",
            province=d.get("province") or (province_name(code) if code else ""),
            province_code=code or "",
            description=d.get("description") or "",
            seller=self.seller_name,
            lat=d.get("lat"),
            lon=d.get("lon"),
        )
