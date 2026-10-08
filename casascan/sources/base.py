"""Clase base de todas las fuentes."""

from __future__ import annotations

import logging
from collections.abc import Iterator

from ..http import HttpClient
from ..models import Listing


class Source:
    #: identificador corto (clave en config.yaml)
    name: str = ""
    #: nombre legible
    label: str = ""
    #: web principal (para el informe)
    homepage: str = ""

    def __init__(self, http: HttpClient, options: dict | None = None, criteria: dict | None = None, cache=None):
        self.http = http
        self.options = options or {}
        self.criteria = criteria or {}
        self.cache = cache  # Storage (opcional) para no reabrir fichas ya leídas
        self.log = logging.getLogger(f"casascan.{self.name}")

    def search(self, provinces: list[str]) -> Iterator[Listing]:
        """Devuelve los resultados de las provincias indicadas (códigos INE)."""
        raise NotImplementedError

    # Ayudas para las subclases ------------------------------------------
    def opt(self, key: str, default=None):
        value = self.options.get(key, default)
        return default if value is None else value

    def cached_detail(self, key: str, fetch) -> list[Listing]:
        """Devuelve la ficha guardada si es reciente; si no, la descarga con fetch() y la guarda."""
        hours = float(self.opt("cache_horas", 24))
        ckey = f"{self.name}:{key}"
        if self.cache is not None and hours > 0:
            data = self.cache.cache_get(ckey, hours)
            if data:
                return [Listing.from_dict(d) for d in data]
        listings = fetch()
        if self.cache is not None and hours > 0 and listings and not any(x.extra.get("_incompleto") for x in listings):
            self.cache.cache_put(ckey, listings)
        return listings

    @property
    def wanted_types(self) -> list[str]:
        return [t for t in (self.criteria.get("tipos") or []) if t]
