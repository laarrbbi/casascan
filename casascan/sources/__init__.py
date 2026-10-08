"""Registro de fuentes disponibles (en el orden en que se recorren)."""

from __future__ import annotations

from .aliseda import AlisedaSource
from .base import Source
from .boe import BoeSource
from .boe_anuncios import BoeAnunciosSource
from .fotocasa import FotocasaSource
from .idealista import IdealistaSource
from .seguridad_social import SeguridadSocialSource
from .servihabitat import ServihabitatSource

SOURCES: dict[str, type[Source]] = {
    cls.name: cls
    for cls in (
        IdealistaSource,
        FotocasaSource,
        AlisedaSource,
        ServihabitatSource,
        BoeSource,
        SeguridadSocialSource,
        BoeAnunciosSource,
    )
}

__all__ = ["SOURCES", "Source"]
