"""Portal de Subastas del BOE (subastas.boe.es).

Aquí están TODAS las subastas electrónicas oficiales: judiciales (los juzgados
de cada provincia), notariales, Agencia Tributaria y otras administraciones.

Flujo:
  1. POST a subastas_ava.php (buscador avanzado) por provincia + estado +
     subtipo de inmueble, siguiendo el enlace "Pág. siguiente".
  2. Para cada subasta, ficha detalleSubasta.php?idSub=...:
       (sin ver) -> datos generales: valor, tasación, puja mínima, depósito, fechas
       ver=3     -> el bien: descripción, dirección, referencia catastral...
                    (con idLote=N si la subasta tiene varios lotes)
       ver=5     -> pujas (opcional)

El portal muestra un captcha si se le hacen muchas peticiones seguidas; por eso
hay pausas entre peticiones y se avisa claramente si aparece.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import BlockedError
from ..models import SUBASTA, Listing
from ..provinces import province_code, province_name
from ..textutil import clean, find_cadastral_ref, norm, parse_date, parse_euros, parse_m2, parse_rooms
from .base import Source

BASE = "https://subastas.boe.es"
SEARCH_URL = f"{BASE}/subastas_ava.php"
DETAIL_URL = f"{BASE}/detalleSubasta.php"

# Subtipos de inmueble del buscador (dato[4])
SUBTIPOS = {
    "vivienda": "501",
    "local": "502",
    "garaje": "503",
    "trastero": "504",
    "nave": "505",
    "solar": "506",
    "rustica": "507",
    "otro": "599",
}
SUBTIPO_NOMBRE = {v: k for k, v in SUBTIPOS.items()}

# Estados (dato[2])
ESTADOS = {
    "PU": "Próxima apertura",
    "EJ": "Celebrándose",
    "SU": "Suspendida",
    "CA": "Cancelada",
    "PC": "Concluida en Portal de Subastas",
    "FS": "Finalizada por Autoridad Gestora",
}

# Origen según el prefijo del identificador SUB-XX-AAAA-NNNN
ORIGEN_POR_PREFIJO = {
    "JA": "judicial", "JV": "judicial", "JC": "judicial",
    "NE": "notarial", "NH": "notarial", "NV": "notarial", "NN": "notarial",
    "AT": "agencia_tributaria",
}


def origin_of(id_sub: str) -> str:
    m = re.match(r"SUB-([A-Z]{2})-", id_sub or "")
    if not m:
        return "otro"
    return ORIGEN_POR_PREFIJO.get(m.group(1), "administrativa")


def property_type_from_text(text: str) -> str:
    t = norm(text)
    for key, typ in (
        ("vivienda", "vivienda"), ("piso", "vivienda"), ("chalet", "vivienda"), ("casa", "vivienda"),
        ("local", "local"), ("garaje", "garaje"), ("aparcamiento", "garaje"),
        ("trastero", "trastero"), ("nave", "nave"), ("industrial", "nave"), ("solar", "solar"),
        ("rustica", "rustica"), ("rustico", "rustica"),
    ):
        if key in t:
            return typ
    return ""


# ---------------------------------------------------------------- parsers
def _table_dict(soup) -> dict[str, str]:
    out: dict[str, str] = {}
    for tr in soup.select("tr"):
        th, td = tr.find("th"), tr.find("td")
        if th and td:
            key = norm(th.get_text(" ")).rstrip(":").strip()
            out.setdefault(key, clean(td.get_text(" ")))
    return out


def parse_search_results(html: str) -> tuple[list[dict], str | None]:
    """Lista de subastas de una página de resultados + href de la página siguiente."""
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen: set[str] = set()
    for li in soup.select("li.resultado-busqueda"):
        h3 = li.find("h3")
        m = re.search(r"(SUB-[A-Z0-9\-]+)", h3.get_text() if h3 else li.get_text())
        if not m:
            continue
        id_sub = m.group(1)
        if id_sub in seen:
            continue
        seen.add(id_sub)
        item = {"id": id_sub, "authority": "", "expediente": "", "status": "", "end_date": "", "summary": ""}
        h4 = li.find("h4")
        if h4:
            item["authority"] = clean(h4.get_text())
        for p in li.find_all("p"):
            t = clean(p.get_text(" "))
            nt = norm(t)
            if nt.startswith("expediente"):
                item["expediente"] = t.split(":", 1)[-1].strip()
            elif nt.startswith("estado"):
                estado = t.split(":", 1)[-1]
                item["status"] = clean(re.split(r"\s-\s|\[", estado)[0])
                fm = re.search(r"(\d{2}/\d{2}/\d{4})\s+a\s+las\s+(\d{2}:\d{2})", t)
                if fm:
                    item["end_date"] = parse_date(f"{fm.group(1)} {fm.group(2)}")
            elif nt.startswith("descripci"):
                item["summary"] = t.split(":", 1)[-1].strip()
        items.append(item)

    if not items:  # formato desconocido: al menos sacar los identificadores
        for id_sub in dict.fromkeys(re.findall(r"idSub=(SUB-[A-Za-z0-9\-]+)", html)):
            items.append({"id": id_sub, "authority": "", "expediente": "", "status": "", "end_date": "", "summary": ""})

    next_href = None
    for a in soup.find_all("a", href=True):
        if "siguiente" in norm(a.get_text(" ")):
            next_href = a["href"]
            break
    return items, next_href


def parse_general(html: str) -> dict:
    """Pestaña general de la ficha (datos económicos y fechas)."""
    soup = BeautifulSoup(html, "lxml")
    c = _table_dict(soup)
    return {
        "tipo_subasta": c.get("tipo de subasta", ""),
        "fecha_inicio": parse_date(c.get("fecha de inicio")),
        "fecha_fin": parse_date(c.get("fecha de conclusion")),
        "cantidad_reclamada": parse_euros(c.get("cantidad reclamada")),
        "valor_subasta": parse_euros(c.get("valor subasta")),
        "tasacion": parse_euros(c.get("tasacion")),
        "puja_minima": parse_euros(c.get("puja minima")),
        "tramos": parse_euros(c.get("tramos entre pujas")),
        "deposito": parse_euros(c.get("importe del deposito")),
        "lotes": c.get("lotes", ""),
        "anuncio_boe": c.get("anuncio boe", ""),
        "cuenta_expediente": c.get("cuenta expediente", ""),
    }


def parse_bien(html: str) -> dict:
    """Pestaña 'Bienes' (ver=3) de la ficha."""
    soup = BeautifulSoup(html, "lxml")
    header = soup.find(["h4", "h3"], string=re.compile(r"Bien\s+\d+"))
    tipo_bien = clean(header.get_text()) if header else ""
    c = _table_dict(soup)
    desc = c.get("descripcion", "")
    desc = re.sub(r"^descripci[oó]n:\s*", "", desc, flags=re.I)
    return {
        "tipo_bien": tipo_bien,
        "descripcion": desc,
        "referencia_catastral": c.get("referencia catastral", "") or find_cadastral_ref(desc),
        "direccion": c.get("direccion", ""),
        "codigo_postal": c.get("codigo postal", ""),
        "localidad": c.get("localidad", ""),
        "provincia": c.get("provincia", ""),
        "situacion_posesoria": c.get("situacion posesoria", ""),
        "visitable": c.get("visitable", ""),
        "vivienda_habitual": c.get("vivienda habitual", ""),
        "cargas": c.get("cargas", ""),
        "inscripcion_registral": c.get("inscripcion registral", ""),
        "idufir": c.get("idufir", "") or c.get("idufir/cru", ""),
        # Con varios lotes, los importes reales de cada lote están aquí
        "valor_subasta_lote": parse_euros(c.get("valor subasta")),
        "tasacion_lote": parse_euros(c.get("valor de tasacion") or c.get("tasacion")),
        "puja_minima_lote": parse_euros(c.get("puja minima")),
        "deposito_lote": parse_euros(c.get("importe del deposito")),
    }


def parse_pujas(html: str) -> dict[int, float | None]:
    """Pestaña de pujas (ver=5): {nº lote: puja máxima o None}."""
    soup = BeautifulSoup(html, "lxml")
    out: dict[int, float | None] = {}
    table = soup.find("table")
    if table and table.find("th", id="lote"):
        for tr in table.select("tbody tr"):
            tds = tr.find_all("td")
            if len(tds) >= 2:
                m = re.search(r"\d+", tds[0].get_text())
                if m:
                    out[int(m.group())] = parse_euros(tds[1].get_text())
        return out
    h4 = soup.find(["h4", "h3"], string=re.compile(r"Puja m.xima", re.I))
    if h4:
        strong = h4.find_next("strong")
        out[1] = parse_euros(strong.get_text()) if strong else None
    elif "no ha recibido pujas" in norm(soup.get_text(" ")) or "sin puja" in norm(soup.get_text(" ")):
        out[1] = None
    return out


def lot_count(lotes_text: str) -> int:
    t = norm(lotes_text)
    if not t or "sin lotes" in t:
        return 1
    m = re.search(r"\d+", t)
    return int(m.group()) if m else 1


# ------------------------------------------------------------------ source
class BoeSource(Source):
    name = "boe"
    label = "Portal de Subastas del BOE (juzgados, notarías, AEAT…)"
    homepage = "https://subastas.boe.es"

    def _subtypes(self) -> list[str]:
        wanted = self.wanted_types
        if not wanted or any(t not in SUBTIPOS for t in wanted):
            return [""]  # todos los inmuebles
        return [SUBTIPOS[t] for t in wanted]

    def _form(self, province: str, status: str, subtype: str) -> dict:
        return {
            "campo[0]": "SUBASTA.ORIGEN", "dato[0]": "",
            "campo[1]": "SUBASTA.AUTORIDAD", "dato[1]": "",
            "campo[2]": "SUBASTA.ESTADO.CODIGO", "dato[2]": status,
            "campo[3]": "BIEN.TIPO", "dato[3]": "I",
            "dato[4]": subtype,
            "campo[5]": "BIEN.DIRECCION", "dato[5]": "",
            "campo[6]": "BIEN.CODPOSTAL", "dato[6]": "",
            "campo[7]": "BIEN.LOCALIDAD", "dato[7]": "",
            "campo[8]": "BIEN.COD_PROVINCIA", "dato[8]": province,
            "page_hits": "50",
            "sort_field[0]": "SUBASTA.FECHA_FIN", "sort_order[0]": "asc",
            "accion": "Buscar",
        }

    def _check(self, html: str, where: str) -> None:
        # La página de verificación no trae ni resultados ni tablas de datos.
        has_content = "resultado-busqueda" in html or "<th" in html or "es excesivo" in html
        if "captcha" in html.lower() and not has_content:
            raise BlockedError(
                f"El BOE ha pedido verificación de seguridad (captcha) en {where}. "
                "Espera un rato (a veces más de 30 min) y sube las pausas en config.yaml (red.pausa_min)."
            )

    def _search_ids(self, province: str, status: str, subtype: str) -> list[dict]:
        form = self._form(province, status, subtype)
        html = self.http.post(SEARCH_URL, data=form).text
        self._check(html, "la búsqueda")
        if "es excesivo" in html:
            if subtype == "":
                self.log.info("Demasiados resultados en %s; se divide por tipo de inmueble", province_name(province))
                out: list[dict] = []
                for st in SUBTIPOS.values():
                    out.extend(self._search_ids(province, status, st))
                return out
            self.log.warning(
                "El BOE dice que hay demasiados resultados (%s, %s, subtipo %s); se omite",
                province_name(province), status, subtype,
            )
            return []
        items, next_href = parse_search_results(html)
        for it in items:
            it["queried_subtype"] = subtype
        pages = 1
        max_pages = int(self.opt("max_paginas", 20))
        while next_href and pages < max_pages:
            html = self.http.get(urljoin(SEARCH_URL, next_href)).text
            self._check(html, "la paginación")
            new, next_href = parse_search_results(html)
            if not new:
                break
            for it in new:
                it["queried_subtype"] = subtype
            items.extend(new)
            pages += 1
        return items

    def _wanted_origin(self, id_sub: str) -> bool:
        origins = [norm(o).replace(" ", "_") for o in self.opt("origenes", []) or []]
        return not origins or origin_of(id_sub) in origins

    def _skip_by_summary(self, item: dict) -> bool:
        excl = [norm(w) for w in self.criteria.get("excluir_palabras") or []]
        text = norm(item.get("summary", ""))
        return any(w and w in text for w in excl)

    def search(self, provinces: list[str]) -> Iterator[Listing]:
        statuses = self.opt("estados", ["PU", "EJ"]) or ["PU", "EJ"]
        with_detail = bool(self.opt("detalle", True))
        limit = self.opt("limite")
        for prov in provinces:
            seen: set[str] = set()
            produced = 0
            for status in statuses:
                for subtype in self._subtypes():
                    items = self._search_ids(prov, status, subtype)
                    self.log.info(
                        "%s · %s · %s: %d subastas",
                        province_name(prov), ESTADOS.get(status, status),
                        SUBTIPO_NOMBRE.get(subtype, "inmuebles"), len(items),
                    )
                    for item in items:
                        if item["id"] in seen or not self._wanted_origin(item["id"]):
                            continue
                        seen.add(item["id"])
                        if self._skip_by_summary(item):
                            continue
                        item["status"] = item["status"] or ESTADOS.get(status, status)
                        if with_detail:
                            listings = self.cached_detail(item["id"], lambda it=item, p=prov: self.detail(it, p))
                            for lst in listings:  # el estado sí cambia (próxima apertura -> celebrándose)
                                lst.status = item["status"]
                        else:
                            listings = [self._from_summary(item, prov)]
                        for lst in listings:
                            yield lst
                            produced += 1
                        if limit and produced >= int(limit):
                            break
                    if limit and produced >= int(limit):
                        break
                if limit and produced >= int(limit):
                    break

    # ----------------------------------------------------------- detail
    def _from_summary(self, item: dict, prov: str) -> Listing:
        subtype = item.get("queried_subtype", "")
        return Listing(
            source=self.name,
            id=item["id"],
            url=f"{DETAIL_URL}?idSub={item['id']}&ver=1",
            kind=SUBASTA,
            title=f"Subasta {item['id']}",
            property_type=SUBTIPO_NOMBRE.get(subtype, "") or property_type_from_text(item.get("summary", "")),
            description=item.get("summary", ""),
            province=province_name(prov),
            province_code=prov,
            status=item.get("status", ""),
            end_date=item.get("end_date", ""),
            seller=item.get("authority", ""),
            extra={"expediente": item.get("expediente", ""), "origen": origin_of(item["id"])},
        )

    def detail(self, item: dict, prov: str) -> list[Listing]:
        id_sub = item["id"]
        try:
            html = self.http.get(DETAIL_URL, params={"idSub": id_sub, "ver": 1}).text
            self._check(html, f"la ficha {id_sub}")
            general = parse_general(html)
            n_lots = lot_count(general["lotes"])
            pujas: dict[int, float | None] = {}
            if self.opt("pujas", False):
                pujas = parse_pujas(self.http.get(DETAIL_URL, params={"idSub": id_sub, "ver": 5}).text)
            out = []
            for lot in range(1, n_lots + 1):
                params = {"idSub": id_sub, "ver": 3}
                if n_lots > 1:
                    params["idLote"] = lot
                bhtml = self.http.get(DETAIL_URL, params=params).text
                self._check(bhtml, f"la ficha {id_sub}")
                bien = parse_bien(bhtml)
                out.append(self._build(item, prov, general, bien, lot, n_lots, pujas.get(lot)))
            return out
        except BlockedError:
            raise
        except Exception as exc:  # una ficha rota no debe parar todo el rastreo
            self.log.warning("No se pudo leer la ficha %s: %s", id_sub, exc)
            fallback = self._from_summary(item, prov)
            fallback.extra["_incompleto"] = True
            return [fallback]

    def _build(self, item, prov, g, b, lot, n_lots, best_bid) -> Listing:
        multi = n_lots > 1
        auction_value = (b["valor_subasta_lote"] if multi else None) or g["valor_subasta"]
        appraisal = (b["tasacion_lote"] if multi else None) or g["tasacion"]
        min_bid = (b["puja_minima_lote"] if multi else None) or g["puja_minima"]
        deposit = (b["deposito_lote"] if multi else None) or g["deposito"]
        ref = str(self.opt("precio_referencia", "valor_subasta"))
        price = {
            "valor_subasta": auction_value or min_bid or appraisal,
            "puja_minima": min_bid or auction_value or appraisal,
            "tasacion": appraisal or auction_value,
        }.get(ref, auction_value or min_bid or appraisal)
        subtype = item.get("queried_subtype", "")
        ptype = SUBTIPO_NOMBRE.get(subtype, "") or property_type_from_text(
            f"{b['tipo_bien']} {b['descripcion'][:200]}"
        )
        prov_txt = b["provincia"] or province_name(prov)
        lot_id = f"{item['id']}-L{lot}" if multi else item["id"]
        url = f"{DETAIL_URL}?idSub={item['id']}&ver=3" + (f"&idLote={lot}" if multi else "")
        return Listing(
            source=self.name,
            id=lot_id,
            url=url,
            kind=SUBASTA,
            title=f"Subasta {item['id']}" + (f" · lote {lot}" if multi else ""),
            property_type=ptype,
            price=price,
            appraisal=appraisal,
            auction_value=auction_value,
            min_bid=min_bid,
            deposit=deposit,
            claimed_debt=g["cantidad_reclamada"],
            surface_m2=parse_m2(b["descripcion"]),
            rooms=parse_rooms(b["descripcion"]),
            address=b["direccion"],
            postal_code=b["codigo_postal"],
            city=b["localidad"],
            province=prov_txt,
            province_code=province_code(prov_txt) or prov,
            cadastral_ref=b["referencia_catastral"],
            status=item.get("status", ""),
            start_date=g["fecha_inicio"],
            end_date=g["fecha_fin"] or item.get("end_date", ""),
            description=b["descripcion"] or item.get("summary", ""),
            seller=item.get("authority", ""),
            extra={
                "origen": origin_of(item["id"]),
                "tipo_subasta": g["tipo_subasta"],
                "expediente": item.get("expediente", ""),
                "anuncio_boe": g["anuncio_boe"],
                "situacion_posesoria": b["situacion_posesoria"],
                "visitable": b["visitable"],
                "vivienda_habitual": b["vivienda_habitual"],
                "cargas": b["cargas"],
                "inscripcion_registral": b["inscripcion_registral"],
                "idufir": b["idufir"],
                "tramos_pujas": g["tramos"],
                "puja_maxima_actual": best_bid,
            },
        )
