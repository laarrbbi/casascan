"""Avisos PREVIOS a la subasta publicados en el Boletín Oficial del Estado.

Antes de que un inmueble salga en el Portal de Subastas suelen publicarse en el
BOE anuncios de notarías (ventas extrajudiciales por impago de hipoteca),
edictos de juzgados, anuncios de la Seguridad Social / Agencia Tributaria sobre
enajenaciones y embargos, etc.

Se usa la API oficial de datos abiertos del BOE (gratuita, sin registro):
    https://www.boe.es/datosabiertos/api/boe/sumario/AAAAMMDD
y se filtran los anuncios por palabras clave y por la provincia/localidades.

Nota sobre el Registro de la Propiedad: no tiene ninguna consulta pública ni
gratuita para saber qué fincas tienen un embargo o una ejecución en curso. La
"nota simple" se pide de una en una (y se paga) en sede.registradores.org.
Lo más parecido y legal son estos anuncios del BOE y las subastas en estado
"Próxima apertura" del Portal de Subastas.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

from ..models import ANUNCIO, Listing
from ..provinces import PROVINCIAS, province_name
from ..textutil import clean, norm
from .base import Source

API = "https://www.boe.es/datosabiertos/api/boe/sumario/{fecha}"

DEFAULT_KEYWORDS = [
    "subasta",
    "ejecucion hipotecaria",
    "venta extrajudicial",
    "enajenacion",
    "apremio",
    "embargo",
]


def _url(value) -> str:
    if isinstance(value, dict):
        value = value.get("texto") or value.get("#text") or ""
    value = str(value or "")
    return f"https://www.boe.es{value}" if value.startswith("/") else value


def iter_items(node, ctx: dict | None = None, key: str | None = None) -> Iterator[tuple[dict, dict]]:
    """Recorre el sumario (cada nivel puede ser objeto o lista) y devuelve
    (item, contexto) con la sección, departamento y epígrafe de cada anuncio."""
    ctx = ctx or {}
    if isinstance(node, list):
        for x in node:
            yield from iter_items(x, ctx, key)
        return
    if not isinstance(node, dict):
        return
    if "identificador" in node and "titulo" in node:
        yield node, ctx
        return
    ctx2 = dict(ctx)
    if key in ("seccion", "departamento", "epigrafe"):
        ctx2[key] = clean(str(node.get("nombre", "")))
        if key == "seccion":
            ctx2["seccion_codigo"] = str(node.get("codigo", ""))
    for k, v in node.items():
        if isinstance(v, (dict, list)):
            yield from iter_items(v, ctx2, k)


def _province_terms(codes: list[str]) -> list[str]:
    terms: list[str] = []
    for c in codes:
        terms += [norm(n) for n in PROVINCIAS[c].split("/")]
    return terms


class BoeAnunciosSource(Source):
    name = "boe_anuncios"
    label = "BOE: anuncios y edictos previos a subasta"
    homepage = "https://www.boe.es"

    def search(self, provinces: list[str]) -> Iterator[Listing]:
        days = int(self.opt("dias", 7))
        keywords = [norm(k) for k in (self.opt("palabras", []) or DEFAULT_KEYWORDS)]
        places = _province_terms(provinces) + [norm(x) for x in self.criteria.get("localidades") or []]
        all_spain = len(provinces) == len(PROVINCIAS)
        today = date.today()
        for delta in range(days):
            day = today - timedelta(days=delta)
            if day.weekday() == 6:  # el BOE no se publica en domingo
                continue
            fecha = day.strftime("%Y%m%d")
            r = self.http.get(API.format(fecha=fecha), headers={"Accept": "application/json"})
            if r.status == 404:
                continue
            if r.status != 200:
                self.log.warning("Sumario BOE %s: HTTP %d", fecha, r.status)
                continue
            n = 0
            for item, ctx in iter_items(r.json().get("data", {})):
                text = norm(" ".join([item.get("titulo", ""), ctx.get("departamento", ""), ctx.get("epigrafe", "")]))
                if not any(k in text for k in keywords):
                    continue
                if not all_spain and not any(p and p in text for p in places):
                    continue
                n += 1
                yield self._build(item, ctx, day, provinces)
            self.log.info("BOE %s: %d anuncios relevantes", day.isoformat(), n)

    def _build(self, item: dict, ctx: dict, day: date, provinces: list[str]) -> Listing:
        ident = item["identificador"]
        text = norm(f"{item.get('titulo', '')} {ctx.get('departamento', '')} {ctx.get('epigrafe', '')}")
        code = next((c for c in provinces if any(t in text for t in _province_terms([c]))), "")
        url = _url(item.get("url_html")) or f"https://www.boe.es/diario_boe/txt.php?id={ident}"
        return Listing(
            source=self.name,
            id=ident,
            url=url,
            kind=ANUNCIO,
            title=clean(item.get("titulo", "")),
            province=province_name(code) if code else "",
            province_code=code,
            start_date=day.isoformat(),
            description=clean(item.get("titulo", "")),
            seller=ctx.get("departamento", ""),
            extra={
                "seccion": f"{ctx.get('seccion_codigo', '')} {ctx.get('seccion', '')}".strip(),
                "epigrafe": ctx.get("epigrafe", ""),
                "pdf": _url(item.get("url_pdf")),
            },
        )
