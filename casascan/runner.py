"""Orquestación: recorre las fuentes una a una, filtra, guarda, informa y avisa."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import catastro
from .config import Config
from .criteria import Criteria
from .http import BlockedError, HttpClient
from .models import ANUNCIO, SUBASTA, Listing
from .notify import send_telegram
from .report import write_reports
from .sources import SOURCES
from .storage import Storage

log = logging.getLogger("casascan")

BLOCK_HINT = (
    " → Prueba con --navegador (o --navegador-visible para resolver el captcha a mano una vez), "
    "instala curl_cffi, o sube las pausas en config.yaml."
)
KIND_ORDER = {SUBASTA: 0, "venta": 1, ANUNCIO: 2}


@dataclass
class RunResult:
    items: list[Listing] = field(default_factory=list)
    stats: dict[str, tuple[int, int]] = field(default_factory=dict)  # fuente -> (vistos, cumplen)
    errors: dict[str, str] = field(default_factory=dict)
    files: list[Path] = field(default_factory=list)
    interrupted: bool = False

    @property
    def new_items(self) -> list[Listing]:
        return [i for i in self.items if i.is_new or i.price_drop]


def run(config: Config, only_sources: list[str] | None = None, limit: int | None = None) -> RunResult:
    criteria = Criteria(config.criteria)
    provinces = sorted(criteria.provinces)
    names = only_sources or config.enabled_sources()
    unknown = [n for n in names if n not in SOURCES]
    if unknown:
        raise ValueError(f"Fuentes desconocidas: {', '.join(unknown)}. Disponibles: {', '.join(SOURCES)}")

    http = HttpClient(config.net)
    storage = Storage(config.output["base_datos"])
    result = RunResult()
    collected: dict[str, Listing] = {}
    try:
        for name in names:
            options = dict(config.source(name))
            if limit:
                options["limite"] = limit
            source = SOURCES[name](http, options, config.criteria, cache=storage)
            log.info("──── %s ────", source.label)
            seen = kept = 0
            try:
                for item in source.search(provinces):
                    seen += 1
                    if criteria.matches(item):
                        kept += 1
                        collected.setdefault(item.key, item)
                    elif log.isEnabledFor(logging.DEBUG):
                        log.debug("descartado %s: %s", item.key, ", ".join(criteria.reasons_to_reject(item)))
            except BlockedError as exc:
                result.errors[name] = f"{exc}{BLOCK_HINT}"
                log.warning("%s bloqueado: %s", source.label, exc)
            except KeyboardInterrupt:
                raise
            except Exception as exc:  # una fuente que falla no tumba el resto
                result.errors[name] = f"{type(exc).__name__}: {exc}"
                log.warning("%s ha fallado: %s", source.label, exc, exc_info=log.isEnabledFor(logging.DEBUG))
            result.stats[name] = (seen, kept)
            log.info("%s: %d vistos, %d cumplen los criterios", source.label, seen, kept)
    except KeyboardInterrupt:
        result.interrupted = True
        log.warning("Interrumpido: se guarda lo encontrado hasta ahora")

    items = list(collected.values())
    if config.data.get("enriquecer_catastro") and not result.interrupted:
        catastro.enrich(items, http)
        items = [i for i in items if criteria.matches(i)]
    http.close()

    try:
        for it in items:
            it.extra.pop("_incompleto", None)
            storage.record(it)
    finally:
        storage.close()

    items.sort(key=lambda i: (not (i.is_new or i.price_drop), KIND_ORDER.get(i.kind, 9), i.price or float("inf")))
    report_items = [i for i in items if i.is_new or i.price_drop] if config.output.get("solo_nuevos") else items
    result.items = items
    result.files = write_reports(
        report_items, config.output["carpeta"], config.output.get("formatos", ["csv", "html"]), result.errors
    )

    tg = config.data.get("notificaciones", {}).get("telegram", {})
    if tg.get("activo") and result.new_items:
        n = send_telegram(result.new_items, tg.get("token", ""), str(tg.get("chat_id", "")))
        log.info("Telegram: %d mensajes enviados", n)
    return result
