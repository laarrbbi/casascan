"""Servihabitat: servicer de pisos de bancos y, desde 2026, de parte de la cartera de la Sareb.

No hay un patrón de URL documentado, así que se descubre el enlace de cada
provincia desde la portada. Si no encuentra nada, haz la búsqueda en
servihabitat.com y pega la URL en config.yaml (fuentes.servihabitat.urls).
"""

from __future__ import annotations

from .servicer import ServicerSource

WEB = "https://www.servihabitat.com"


class ServihabitatSource(ServicerSource):
    name = "servihabitat"
    label = "Servihabitat (bancos y Sareb)"
    homepage = WEB
    home_url = f"{WEB}/es"
    seller_name = "Servihabitat"
    discovery_pages = (f"{WEB}/es", f"{WEB}/")
    link_hints = ("venta", "comprar", "viviendas", "inmuebles")
    url_templates = (
        f"{WEB}/es/venta/viviendas/{{prov}}",
        f"{WEB}/es/comprar/viviendas/{{prov}}",
    )
    page_param = "page"
