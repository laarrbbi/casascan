"""Modelo común para todo lo que sacan las fuentes (anuncios, subastas, edictos)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any

# Tipos de resultado
VENTA = "venta"        # inmueble en venta (portales, servicers de bancos/Sareb)
SUBASTA = "subasta"    # subasta judicial / notarial / administrativa
ANUNCIO = "anuncio"    # edicto o anuncio oficial previo a la subasta

# Tipos de inmueble normalizados
TIPOS_INMUEBLE = ("vivienda", "local", "garaje", "trastero", "nave", "solar", "rustica", "edificio", "otro")


@dataclass
class Listing:
    source: str                    # 'boe', 'seguridad_social', 'idealista', ...
    id: str                        # identificador único dentro de la fuente
    url: str
    kind: str = VENTA
    title: str = ""
    property_type: str = ""        # uno de TIPOS_INMUEBLE ('' si no se sabe)
    price: float | None = None     # precio de venta o importe de referencia de la subasta
    appraisal: float | None = None  # tasación
    auction_value: float | None = None  # valor de subasta
    min_bid: float | None = None   # puja mínima
    deposit: float | None = None   # depósito para pujar
    claimed_debt: float | None = None  # cantidad reclamada / cargas
    surface_m2: float | None = None
    rooms: int | None = None
    bathrooms: int | None = None
    address: str = ""
    postal_code: str = ""
    city: str = ""
    province: str = ""
    province_code: str = ""
    cadastral_ref: str = ""
    status: str = ""               # estado de la subasta
    start_date: str = ""           # ISO 8601
    end_date: str = ""             # ISO 8601
    description: str = ""
    seller: str = ""               # autoridad gestora / juzgado / banco / agencia
    lat: float | None = None
    lon: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    # Rellenados por el almacenamiento (no por las fuentes)
    is_new: bool = False
    previous_price: float | None = None
    first_seen: str = ""

    @property
    def key(self) -> str:
        return f"{self.source}:{self.id}"

    @property
    def price_per_m2(self) -> float | None:
        if self.price and self.surface_m2:
            return round(self.price / self.surface_m2, 2)
        return None

    @property
    def discount_pct(self) -> float | None:
        """Descuento del precio frente a la tasación (solo si hay tasación)."""
        if self.price and self.appraisal and self.appraisal > 0:
            return round(100 * (1 - self.price / self.appraisal), 1)
        return None

    @property
    def price_drop(self) -> bool:
        return bool(self.previous_price and self.price and self.price < self.previous_price)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["price_per_m2"] = self.price_per_m2
        d["discount_pct"] = self.discount_pct
        d["price_drop"] = self.price_drop
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Listing":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})
