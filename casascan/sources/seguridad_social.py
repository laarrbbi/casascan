"""Subastas de bienes embargados de la Seguridad Social (TGSS).

Web: https://w6.seg-social.es/subastas/SubaSeControladorInter

Es una aplicación Java antigua con sesión (cookie JSESSIONID):
  1. GET  ?opcion=6&avanzada=1           -> abre la sesión (si no, da error)
  2. POST opcion=7 con EMB_TIPOBIEN y provincia -> listado en tablas por tipo de
     bien y provincia (nombre, tasación, cargas, lote, valor, fecha subasta, EMB_ID)
     Las páginas siguientes: GET ?opcion=7&pagina=N
  3. GET  ?opcion=13&EMB_ID=X&opcion2=1&tipoOperacion=0 -> ficha con descripción
     y localización.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from bs4 import BeautifulSoup

from ..models import SUBASTA, Listing
from ..provinces import province_code, province_name
from ..textutil import clean, find_cadastral_ref, norm, parse_date, parse_euros, parse_m2, parse_rooms
from .base import Source
from .boe import property_type_from_text

BASE = "https://w6.seg-social.es/subastas/SubaSeControladorInter"

TIPOS_BIEN = {"rustica": "0101", "urbana": "0102"}
RANGE_FIELDS = [
    "CAMPO_TASACION_DESDE", "CAMPO_TASACION_HASTA",
    "CAMPO_CARGAS_DESDE", "CAMPO_CARGAS_HASTA",
    "CAMPO_FSUBASTA_DESDE", "CAMPO_FSUBASTA_HASTA",
    "CAMPO_LICITACION_DESDE", "CAMPO_LICITACION_HASTA",
]
ERROR_MARK = "ERROR en la Aplicaci"

# Posición de cada dato en las filas del listado (si no hay cabeceras reconocibles)
_DEFAULT_COLS = {"nombre": 0, "tasacion": 2, "cargas": 3, "lote": 4, "valor": 5, "fecha": 6}
_HEADER_KEYS = {
    "tasacion": "tasacion", "cargas": "cargas", "lote": "lote",
    "valor": "valor", "licitacion": "valor", "enajenacion": "valor", "fecha": "fecha",
}


def _column_map(table) -> dict[str, int]:
    heads = [norm(th.get_text(" ")) for th in table.select("thead th")] or [
        norm(th.get_text(" ")) for th in table.select("tr th")
    ]
    cols: dict[str, int] = {}
    for i, h in enumerate(heads):
        for key, field in _HEADER_KEYS.items():
            if key in h:  # cada cabecera se asigna al primer dato que encaja
                cols.setdefault(field, i)
                break
    if len(cols) < 3:
        return dict(_DEFAULT_COLS)
    cols.setdefault("nombre", 0)
    return cols


def parse_listing_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    tables = soup.select("div.tablas-resultados table") or soup.select("table")
    for table in tables:
        caption = table.find("caption")
        tipo_bien = provincia = ""
        if caption:
            parts = [clean(p) for p in caption.get_text(" ").split(" - ")]
            if len(parts) >= 2:
                tipo_bien, provincia = parts[0], parts[1]
        cols = _column_map(table)
        rows = table.select("tbody tr") or table.select("tr")
        for tr in rows:
            tds = tr.find_all("td")
            if len(tds) < 4:
                continue
            link = tr.find("a", href=re.compile(r"EMB_ID=\d+"))
            if not link:
                continue
            emb_id = re.search(r"EMB_ID=(\d+)", link["href"]).group(1)

            def cell(field: str, tds=tds, cols=cols) -> str:
                i = cols.get(field)
                return clean(tds[i].get_text(" ")) if i is not None and i < len(tds) else ""

            out.append(
                {
                    "emb_id": emb_id,
                    "nombre": clean(link.get_text(" ")),
                    "tipo_bien": tipo_bien,
                    "provincia": provincia,
                    "tasacion": parse_euros(cell("tasacion")),
                    "cargas": parse_euros(cell("cargas")),
                    "lote": cell("lote"),
                    "valor": parse_euros(cell("valor")),
                    "fecha": cell("fecha"),
                }
            )
    return out


def parse_detail(html: str) -> dict[str, list[str]]:
    """Pares dt/dd de la ficha (algunos dt, como 'Localización', traen varios dd)."""
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, list[str]] = {}
    key = None
    for el in soup.select("dl dt, dl dd"):
        if el.name == "dt":
            key = norm(el.get_text(" ")).rstrip(":")
            out.setdefault(key, [])
        elif key:
            out[key].append(clean(el.get_text(" ")))
    return out


class SeguridadSocialSource(Source):
    name = "seguridad_social"
    label = "Subastas de la Seguridad Social (TGSS)"
    homepage = "https://w6.seg-social.es/subastas/SubaSeControladorInter?opcion=5"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._session_ready = False

    def _ensure_session(self) -> None:
        if not self._session_ready:
            self.http.get(BASE, params={"opcion": 6, "avanzada": 1}, encoding="iso-8859-1")
            self._session_ready = True

    def _bien_codes(self) -> list[str]:
        wanted = self.wanted_types
        if not wanted:
            return list(TIPOS_BIEN.values())
        codes = []
        if any(t != "rustica" for t in wanted):
            codes.append(TIPOS_BIEN["urbana"])
        if "rustica" in wanted or "solar" in wanted:
            codes.append(TIPOS_BIEN["rustica"])
        return codes

    def _search(self, prov: str, retry: bool = True) -> list[dict]:
        self._ensure_session()
        fields: list[tuple[str, str]] = [("opcion", "7")]
        fields += [("EMB_TIPOBIEN", c) for c in self._bien_codes()]
        fields += [(f, "") for f in RANGE_FIELDS]
        fields += [("provincia", prov), ("Aceptar", "Comenzar Busqueda")]
        html = self.http.post(BASE, data=fields, encoding="iso-8859-1").text
        if ERROR_MARK in html:
            if retry:
                self.http.reset_session()
                self._session_ready = False
                return self._search(prov, retry=False)
            self.log.warning("La web de la Seguridad Social devolvió error para %s", province_name(prov))
            return []
        lots = parse_listing_page(html)
        page = 2
        max_pages = int(self.opt("max_paginas", 20))
        while lots and page <= max_pages:
            html = self.http.get(BASE, params={"opcion": 7, "pagina": page}, encoding="iso-8859-1").text
            if ERROR_MARK in html:
                self.log.warning("Error de sesión en la página %d; se corta la paginación", page)
                break
            new = parse_listing_page(html)
            if not new or {n["emb_id"] for n in new} <= {lot["emb_id"] for lot in lots}:
                break
            lots.extend(new)
            page += 1
        return lots

    def search(self, provinces: list[str]) -> Iterator[Listing]:
        limit = self.opt("limite")
        for prov in provinces:
            lots = self._search(prov)
            self.log.info("%s: %d lotes", province_name(prov), len(lots))
            seen: set[str] = set()
            for n, lot in enumerate(lots):
                if lot["emb_id"] in seen:
                    continue
                seen.add(lot["emb_id"])
                if limit and n >= int(limit):
                    break
                if self.opt("detalle", True):
                    yield from self.cached_detail(lot["emb_id"], lambda lot=lot, p=prov: [self._with_detail(lot, p)])
                else:
                    yield self._build(lot, {}, prov)

    def _with_detail(self, lot: dict, prov: str) -> Listing:
        try:
            html = self.http.get(
                BASE,
                params={"opcion": 13, "EMB_ID": lot["emb_id"], "opcion2": 1, "tipoOperacion": 0},
                encoding="iso-8859-1",
            ).text
        except Exception as exc:
            self.log.warning("Sin detalle para EMB_ID=%s: %s", lot["emb_id"], exc)
            item = self._build(lot, {}, prov)
            item.extra["_incompleto"] = True
            return item
        return self._build(lot, parse_detail(html), prov)

    def _build(self, lot: dict, d: dict[str, list[str]], prov: str) -> Listing:
        def first(*keys: str) -> str:
            for k in keys:
                for dk, values in d.items():
                    if dk.startswith(k) and values:
                        return values[0]
            return ""

        loc = next((v for k, v in d.items() if k.startswith("localizacion")), [])
        address = loc[0] if loc else ""
        city = ""
        if len(loc) > 1:
            m = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", loc[1])
            city = m.group(1).strip() if m else loc[1]
        elif address:
            m = re.search(r"\((\d{5})\)\s*(.+)$", address)
            if m:
                city = m.group(2).strip()
        cp = re.search(r"\((\d{5})\)", address)
        desc = first("descripcion detallada", "descripcion") or lot["nombre"]
        prov_txt = lot["provincia"] or province_name(prov)
        ptype = property_type_from_text(f"{lot['nombre']} {desc[:200]}")
        if not ptype and "rustica" in norm(lot["tipo_bien"]):
            ptype = "rustica"
        return Listing(
            source=self.name,
            id=lot["emb_id"],
            url=f"{BASE}?opcion=13&EMB_ID={lot['emb_id']}&opcion2=1&tipoOperacion=0",
            kind=SUBASTA,
            title=lot["nombre"] or f"Lote {lot['emb_id']}",
            property_type=ptype,
            price=lot["valor"] or lot["tasacion"],
            appraisal=lot["tasacion"],
            auction_value=lot["valor"],
            claimed_debt=lot["cargas"],
            surface_m2=parse_m2(desc),
            rooms=parse_rooms(desc),
            address=address,
            postal_code=cp.group(1) if cp else "",
            city=city,
            province=prov_txt,
            province_code=province_code(prov_txt) or prov,
            cadastral_ref=find_cadastral_ref(desc),
            status="Próxima subasta" if lot["fecha"] else "",
            end_date=parse_date(first("fecha") or lot["fecha"]),
            description=desc,
            seller="Tesorería General de la Seguridad Social",
            extra={
                "tipo_bien": lot["tipo_bien"],
                "lote": lot["lote"],
                "expediente": first("expediente"),
                "unidad_recaudacion": first("unidad"),
                "nota": "Puja en sobre cerrado en la Dirección Provincial; depósito habitual 25% del tipo.",
            },
        )
