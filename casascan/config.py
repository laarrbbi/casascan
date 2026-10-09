"""Carga de la configuración (config.yaml) con valores por defecto."""

from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "criterios": {
        "provincias": ["Madrid"],
        "localidades": [],
        "codigos_postales": [],
        "tipos": ["vivienda"],
        "precio_min": None,
        "precio_max": None,
        "superficie_min": None,
        "superficie_max": None,
        "habitaciones_min": None,
        "descuento_min": None,
        "palabras_clave": [],
        "excluir_palabras": [
            "nuda propiedad",
            "usufructo",
            "aprovechamiento por turnos",
            "multipropiedad",
            "derecho de uso",
        ],
        "estricto": False,
    },
    "fuentes": {
        "boe": {
            "activo": True,
            "estados": ["PU", "EJ"],
            "origenes": [],
            "detalle": True,
            "pujas": False,
            "max_paginas": 20,
            "cache_horas": 24,
        },
        "seguridad_social": {"activo": True, "detalle": True, "max_paginas": 20, "cache_horas": 24},
        "idealista": {"activo": True, "solo_bancos": False, "urls": [], "max_paginas": 3},
        "fotocasa": {"activo": True, "urls": [], "max_paginas": 3},
        "aliseda": {"activo": True, "urls": [], "max_paginas": 5},
        "servihabitat": {"activo": True, "urls": [], "max_paginas": 5},
        "boe_anuncios": {"activo": True, "dias": 7, "palabras": []},
    },
    "red": {
        "pausa_min": 2.0,
        "pausa_max": 4.0,
        "timeout": 30,
        "reintentos": 3,
        "navegador": False,
        "navegador_visible": False,
        "perfil_navegador": ".casascan_navegador",
    },
    "salida": {
        "carpeta": "resultados",
        "formatos": ["csv", "html", "json"],
        "solo_nuevos": False,
        "base_datos": "casascan.db",
    },
    "enriquecer_catastro": True,
    "notificaciones": {
        "telegram": {"activo": "auto", "token": "${TELEGRAM_TOKEN}", "chat_id": "${TELEGRAM_CHAT_ID}"},
    },
}

_ENV = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    return value


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_raw(path: str | Path | None) -> dict:
    """config.yaml tal cual (sin valores por defecto ni variables de entorno expandidas)."""
    if path and Path(path).exists():
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    return {}


def save_raw(path: str | Path, data: dict) -> None:
    Path(path).write_text(
        "# Configuración de CasaScan (editada desde la plataforma)\n"
        + yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


class Config:
    def __init__(self, data: dict | None = None):
        self.data = _expand_env(deep_merge(DEFAULTS, data or {}))

    @classmethod
    def load(cls, path: str | Path | None) -> "Config":
        if path and Path(path).exists():
            with open(path, encoding="utf-8") as fh:
                return cls(yaml.safe_load(fh) or {})
        return cls()

    @property
    def criteria(self) -> dict:
        return self.data["criterios"]

    @property
    def net(self) -> dict:
        return self.data["red"]

    @property
    def output(self) -> dict:
        return self.data["salida"]

    def source(self, name: str) -> dict:
        return self.data["fuentes"].get(name, {})

    def enabled_sources(self) -> list[str]:
        return [n for n, c in self.data["fuentes"].items() if c.get("activo", True)]
