"""Aplicación de los criterios de búsqueda a los resultados de todas las fuentes."""

from __future__ import annotations

from .models import ANUNCIO, Listing
from .provinces import resolve_provinces
from .textutil import norm


class Criteria:
    def __init__(self, data: dict):
        self.data = data
        self.provinces = set(resolve_provinces(data.get("provincias")))
        self.cities = [norm(x) for x in data.get("localidades") or []]
        self.postal_codes = [str(x).strip() for x in data.get("codigos_postales") or []]
        self.types = [norm(t) for t in data.get("tipos") or []]
        self.price_min = data.get("precio_min")
        self.price_max = data.get("precio_max")
        self.surface_min = data.get("superficie_min")
        self.surface_max = data.get("superficie_max")
        self.rooms_min = data.get("habitaciones_min")
        self.discount_min = data.get("descuento_min")
        self.keywords = [norm(k) for k in data.get("palabras_clave") or []]
        self.excluded = [norm(k) for k in data.get("excluir_palabras") or []]
        self.strict = bool(data.get("estricto", False))

    def reasons_to_reject(self, item: Listing) -> list[str]:
        """Lista de motivos por los que el resultado NO cumple (vacía = cumple).

        Si a un resultado le falta un dato (p. ej. el BOE no siempre dice los
        m²), solo se descarta en modo `estricto`.
        """
        why: list[str] = []
        text = norm(f"{item.title} {item.description} {item.address} {item.city}")

        def check(value, ok: bool, label: str):
            if value is None:
                if self.strict:
                    why.append(f"sin dato: {label}")
            elif not ok:
                why.append(label)

        if item.province_code and self.provinces and item.province_code not in self.provinces:
            why.append("provincia")
        if self.cities:
            place = text if item.kind == ANUNCIO else norm(f"{item.city} {item.address} {item.title}")
            known = item.kind == ANUNCIO or bool(item.city or item.address)
            check(place if known else None, any(c in place for c in self.cities), "localidad")
        if self.postal_codes and item.postal_code and item.postal_code not in self.postal_codes:
            why.append("código postal")
        if self.excluded and any(w and w in text for w in self.excluded):
            why.append("palabra excluida")
        if self.keywords and not any(k in text for k in self.keywords):
            why.append("sin palabras clave")

        if item.kind == ANUNCIO:  # los edictos no traen precio ni superficie
            return why

        if self.types:
            check(item.property_type or None, norm(item.property_type) in self.types, "tipo")
        if self.price_max is not None:
            check(item.price, item.price is not None and item.price <= float(self.price_max), "precio máximo")
        if self.price_min is not None:
            check(item.price, item.price is not None and item.price >= float(self.price_min), "precio mínimo")
        if self.surface_min is not None:
            check(item.surface_m2, item.surface_m2 is not None and item.surface_m2 >= float(self.surface_min),
                  "superficie mínima")
        if self.surface_max is not None:
            check(item.surface_m2, item.surface_m2 is not None and item.surface_m2 <= float(self.surface_max),
                  "superficie máxima")
        if self.rooms_min is not None:
            check(item.rooms, item.rooms is not None and item.rooms >= int(self.rooms_min), "habitaciones")
        if self.discount_min is not None and item.appraisal:
            d = item.discount_pct
            check(d, d is not None and d >= float(self.discount_min), "descuento sobre tasación")
        return why

    def matches(self, item: Listing) -> bool:
        return not self.reasons_to_reject(item)
