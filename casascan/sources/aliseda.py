"""Aliseda Inmobiliaria: comercializa los inmuebles de la Sareb (y de Santander).

Las páginas de provincia siguen el patrón
https://www.alisedainmobiliaria.com/comprar-viviendas/<comunidad>/<provincia>
(en inglés: /en/buy-homes/<comunidad>/<provincia>) y paginan con ?page=N.
"""

from __future__ import annotations

from .servicer import ServicerSource

WEB = "https://www.alisedainmobiliaria.com"


class AlisedaSource(ServicerSource):
    name = "aliseda"
    label = "Aliseda Inmobiliaria (Sareb)"
    homepage = WEB
    home_url = WEB
    seller_name = "Aliseda / Sareb"
    discovery_pages = (f"{WEB}/", f"{WEB}/comprar-viviendas")
    link_hints = ("comprar-viviendas", "buy-homes")
    url_templates = (
        f"{WEB}/comprar-viviendas/{{ccaa}}/{{prov}}",
        f"{WEB}/en/buy-homes/{{ccaa}}/{{prov}}",
    )
    page_param = "page"
