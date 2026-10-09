"""Orquestación: recorre las fuentes una a una, filtra, guarda, informa y avisa."""

from __future__ import annotations

import logging
from collections.abc import Callable
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


class StopRequested(Exception):
    """El usuario ha pedido parar la búsqueda (botón Detener de la plataforma)."""


@dataclass
class RunResult:
    items: list[Listing] = field(default_factory=list)
    stats: dict[str, tuple[int, int]] = field(default_factory=dict)  # fuente -> (vistos, cumplen)
    errors: dict[str, str] = field(default_factory=dict)
    files: list[Path] = field(default_factory=list)
    interrupted: bool = False
    run_id: int | None = None

    @property
    def new_items(self) -> list[Listing]:
        return [i for i in self.items if i.is_new or i.price_drop]


def run(
    config: Config,
    only_sources: list[str] | None = None,
    limit: int | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> RunResult:
    criteria = Criteria(config.criteria)
    provinces = sorted(criteria.provinces)
    names = only_sources or config.enabled_sources()
    unknown = [n for n in names if n not in SOURCES]
    if unknown:
        raise ValueError(f"Fuentes desconocidas: {', '.join(unknown)}. Disponibles: {', '.join(SOURCES)}")

    def check_stop() -> None:
        if should_stop and should_stop():
            raise StopRequested()

    http = HttpClient(config.net)
    storage = Storage(config.output["base_datos"])
    result = RunResult(run_id=storage.start_run(names))
    collected: dict[str, Listing] = {}
    try:
        try:
            for name in names:
                check_stop()
                options = dict(config.source(name))
                if limit:
                    options["limite"] = limit
                source = SOURCES[name](http, options, config.criteria, cache=storage)
                log.info("──── %s ────", source.label)
                seen = kept = 0
                try:
                    for item in source.search(provinces):
                        check_stop()
                        seen += 1
                        if criteria.matches(item):
                            kept += 1
                            collected.setdefault(item.key, item)
                        elif log.isEnabledFor(logging.DEBUG):
                            log.debug("descartado %s: %s", item.key, ", ".join(criteria.reasons_to_reject(item)))
                except BlockedError as exc:
                    result.errors[name] = f"{exc}{BLOCK_HINT}"
                    log.warning("%s bloqueado: %s", source.label, exc)
                except (KeyboardInterrupt, StopRequested):
                    result.stats[name] = (seen, kept)
                    raise
                except Exception as exc:  # una fuente que falla no tumba el resto
                    result.errors[name] = f"{type(exc).__name__}: {exc}"
                    log.warning("%s ha fallado: %s", source.label, exc, exc_info=log.isEnabledFor(logging.DEBUG))
                result.stats[name] = (seen, kept)
                log.info("%s: %d vistos, %d cumplen los criterios", source.label, seen, kept)
        except (KeyboardInterrupt, StopRequested):
            result.interrupted = True
            log.warning("Búsqueda detenida: se guarda lo encontrado hasta ahora")

        items = list(collected.values())
        if config.data.get("enriquecer_catastro") and not result.interrupted:
            catastro.enrich(items, http)
            items = [i for i in items if criteria.matches(i)]

        for it in items:
            it.extra.pop("_incompleto", None)
            storage.record(it, run_id=result.run_id)
        storage.commit()

        items.sort(key=lambda i: (not (i.is_new or i.price_drop), KIND_ORDER.get(i.kind, 9), i.price or float("inf")))
        report_items = [i for i in items if i.is_new or i.price_drop] if config.output.get("solo_nuevos") else items
        result.items = items
        result.files = write_reports(
            report_items, config.output["carpeta"], config.output.get("formatos", ["csv", "html"]), result.errors
        )
        storage.finish_run(
            result.run_id, {k: list(v) for k, v in result.stats.items()}, result.errors,
            result.interrupted, len(items), len(result.new_items),
        )
    except BaseException as exc:
        storage.finish_run(result.run_id, {k: list(v) for k, v in result.stats.items()},
                           {**result.errors, "_": f"{type(exc).__name__}: {exc}"}, True, 0, 0)
        raise
    finally:
        http.close()
        storage.close()

    tg = config.data.get("notificaciones", {}).get("telegram", {})
    active = tg.get("activo")
    if str(active).lower() == "auto":  # se activa solo si hay token y chat id
        active = bool(tg.get("token") and tg.get("chat_id"))
    if active is True and result.new_items:
        n = send_telegram(result.new_items, tg.get("token", ""), str(tg.get("chat_id", "")))
        log.info("Telegram: %d mensajes enviados", n)
    return result
