"""Enriquecimiento opcional con el Catastro (servicio web público y gratuito).

Para los resultados que traen referencia catastral (muchas subastas) consulta
superficie construida, uso y año de construcción:
https://ovc.catastro.meh.es/ovcservweb/OVCSWLocalizacionRC/OVCCallejero.asmx/Consulta_DNPRC
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

from .http import HttpClient
from .models import Listing

log = logging.getLogger("casascan.catastro")
DNPRC = "https://ovc.catastro.meh.es/ovcservweb/OVCSWLocalizacionRC/OVCCallejero.asmx/Consulta_DNPRC"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_dnprc(xml_text: str) -> dict:
    """Extrae uso, superficie y año del XML de Consulta_DNPRC (ignora namespaces).

    Si la referencia es de una parcela (14 caracteres) con varios inmuebles, la
    respuesta solo trae la lista; en ese caso se devuelve {'inmuebles': N}.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}
    values: dict[str, str] = {}
    for el in root.iter():
        name = _local(el.tag)
        if name in ("luso", "sfc", "ant", "ldt", "cucons", "des") and el.text and name not in values:
            values[name] = el.text.strip()
    out: dict = {}
    if "luso" in values:
        out["uso"] = values["luso"]
    if "sfc" in values and values["sfc"].isdigit():
        out["superficie_m2"] = float(values["sfc"])
    if "ant" in values and values["ant"].isdigit():
        out["anio_construccion"] = int(values["ant"])
    if "ldt" in values:
        out["direccion_catastro"] = values["ldt"]
    if "cucons" in values and not out:
        out["inmuebles"] = int(values["cucons"]) if values["cucons"].isdigit() else values["cucons"]
    if "des" in values and not out:
        out["error"] = values["des"]
    return out


def enrich(items: list[Listing], http: HttpClient) -> None:
    for it in items:
        if not it.cadastral_ref or it.extra.get("catastro"):
            continue
        try:
            r = http.get(DNPRC, params={"Provincia": "", "Municipio": "", "RC": it.cadastral_ref}, check_block=False)
        except Exception as exc:
            log.info("Catastro no disponible para %s: %s", it.cadastral_ref, exc)
            continue
        data = parse_dnprc(r.text)
        if not data:
            continue
        it.extra["catastro"] = data
        if not it.surface_m2 and data.get("superficie_m2"):
            it.surface_m2 = data["superficie_m2"]
        if not it.address and data.get("direccion_catastro"):
            it.address = data["direccion_catastro"]
