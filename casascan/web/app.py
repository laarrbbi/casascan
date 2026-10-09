"""Plataforma web de CasaScan (Flask).

    python -m casascan web         ->  http://127.0.0.1:8000

Sirve la interfaz (carpeta static/) y una API JSON:

    GET  /api/meta                      fuentes, provincias, tipos…
    GET  /api/resumen                   cifras, última búsqueda, trabajo en curso
    GET  /api/inmuebles                 todo lo encontrado (con marcas y estados)
    GET  /api/inmuebles/<key>/historial historial de precios
    POST /api/inmuebles/<key>/marca     {"marca": "favorito", "nota": "…"}
    GET  /api/config | PUT /api/config  criterios, fuentes y ajustes
    POST /api/busqueda                  lanza una búsqueda   ({"fuentes": [...]})
    POST /api/busqueda/detener          la detiene
    GET  /api/trabajo?desde=N           progreso y log en directo
    GET  /api/historial                 búsquedas anteriores
    POST /api/diagnostico               diagnóstico de las webs
    POST /api/telegram/prueba           mensaje de prueba
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request, send_from_directory

from .. import __version__
from ..config import DEFAULTS, Config, deep_merge, load_raw, save_raw
from ..models import TIPOS_INMUEBLE
from ..provinces import CCAA_DE, CCAA_PROVINCIAS, PROVINCIAS, resolve_provinces
from ..sources import SOURCES
from ..storage import MARK_STATES, Storage
from .jobs import JobManager

STATIC = Path(__file__).parent / "static"
log = logging.getLogger("casascan.web")

# Opciones de cada fuente que se pueden editar desde la web
EDITABLE_SOURCE_OPTIONS = {
    "activo": bool, "urls": list, "max_paginas": int, "estados": list, "origenes": list,
    "solo_bancos": bool, "dias": int, "detalle": bool, "precio_referencia": str,
}
CRITERIA_TYPES = {
    "provincias": list, "localidades": list, "codigos_postales": list, "tipos": list,
    "precio_min": float, "precio_max": float, "superficie_min": float, "superficie_max": float,
    "habitaciones_min": int, "descuento_min": float, "palabras_clave": list, "excluir_palabras": list,
    "estricto": bool,
}
DESCRIPTION_MAX = 1500


def _coerce(value: Any, typ: type, field: str) -> Any:
    if value in (None, ""):
        return [] if typ is list else (False if typ is bool else None)
    try:
        if typ is list:
            if isinstance(value, str):
                value = [v.strip() for v in value.split(",")]
            return [str(v).strip() for v in value if str(v).strip()]
        if typ is bool:
            return bool(value) if not isinstance(value, str) else value.lower() in ("1", "true", "si", "sí")
        return typ(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Valor no válido para {field}: {value!r}") from exc


LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1", "[::1]")


def create_app(
    config_path: str = "config.yaml",
    scheduler: bool = True,
    password: str | None = None,
    allow_any_host: bool = False,
) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["CONFIG_PATH"] = config_path
    app.json.ensure_ascii = False
    jobs = JobManager()
    app.extensions["casascan_jobs"] = jobs
    password = password if password is not None else os.environ.get("CASASCAN_PASSWORD", "")

    def cfg() -> Config:
        return Config.load(config_path)

    def storage() -> Storage:
        return Storage(cfg().output["base_datos"])

    # ------------------------------------------------------------ seguridad
    @app.before_request
    def _guard():
        # Sin contraseña solo se atiende a peticiones dirigidas a este ordenador
        # (evita que una web maliciosa lea la plataforma con "DNS rebinding").
        if not password and not allow_any_host and request.host.rsplit(":", 1)[0] not in LOCAL_HOSTS:
            return Response("Acceso solo desde este ordenador", 403)
        if password:
            auth = request.authorization
            if not auth or not hmac.compare_digest(str(auth.password or ""), password):
                return Response("Acceso restringido", 401, {"WWW-Authenticate": 'Basic realm="CasaScan"'})
        # Las peticiones que cambian algo deben ser JSON: un formulario de otra web
        # no puede enviarlas sin permiso CORS (protección CSRF).
        if request.method in ("POST", "PUT", "DELETE") and not request.is_json:
            return jsonify(error="La petición debe ser JSON"), 415
        return None

    @app.errorhandler(ValueError)
    def _bad_request(exc):
        return jsonify(error=str(exc)), 400

    # ------------------------------------------------------------- interfaz
    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/static/<path:name>")
    def static_files(name: str):
        return send_from_directory(STATIC, name)

    # ------------------------------------------------------------------ API
    @app.get("/api/meta")
    def meta():
        return jsonify(build_meta())

    @app.get("/api/resumen")
    def resumen():
        st = storage()
        try:
            items = [i for i in st.listings() if i["vigente"]]
            runs = st.runs(1)
        finally:
            st.close()
        out = summarize(items)
        out["ultima_busqueda"] = runs[0] if runs else None
        out["proxima_busqueda"] = next_auto_run(cfg(), runs[0] if runs else None)
        out["trabajo"] = jobs.snapshot(since=10**9)
        return jsonify(out)

    @app.get("/api/inmuebles")
    def inmuebles():
        st = storage()
        try:
            items = st.listings()
        finally:
            st.close()
        return jsonify([trim(i) for i in items])

    @app.get("/api/inmuebles/<path:key>/historial")
    def historial_precio(key: str):
        st = storage()
        try:
            return jsonify(st.price_history(key))
        finally:
            st.close()

    @app.post("/api/inmuebles/<path:key>/marca")
    def marca(key: str):
        body = request.get_json(silent=True) or {}
        estado = body.get("marca")
        if estado is not None and estado not in MARK_STATES:
            raise ValueError(f"Marca no válida: {estado}")
        st = storage()
        try:
            return jsonify(st.set_mark(key, estado=estado, nota=body.get("nota")))
        finally:
            st.close()

    @app.get("/api/config")
    def get_config():
        return jsonify(editable_config(load_raw(config_path)))

    @app.put("/api/config")
    def put_config():
        body = request.get_json(silent=True) or {}
        raw = apply_config_changes(load_raw(config_path), body)
        save_raw(config_path, raw)
        return jsonify(editable_config(raw))

    @app.post("/api/busqueda")
    def busqueda():
        body = request.get_json(silent=True) or {}
        fuentes = body.get("fuentes") or None
        if fuentes and any(f not in SOURCES for f in fuentes):
            raise ValueError("Fuente desconocida")
        if not start_search(jobs, config_path, fuentes, origin="manual"):
            return jsonify(error="Ya hay un trabajo en marcha"), 409
        return jsonify(ok=True, trabajo=jobs.snapshot()), 202

    @app.post("/api/busqueda/detener")
    def detener():
        return jsonify(ok=jobs.stop())

    @app.get("/api/trabajo")
    def trabajo():
        since = request.args.get("desde", default=0, type=int)
        return jsonify(jobs.snapshot(since=since))

    @app.get("/api/historial")
    def historial():
        st = storage()
        try:
            return jsonify(st.runs(50))
        finally:
            st.close()

    @app.post("/api/diagnostico")
    def diagnostico():
        body = request.get_json(silent=True) or {}
        conf = cfg()
        fuentes = body.get("fuentes") or conf.enabled_sources()
        if any(f not in SOURCES for f in fuentes):
            raise ValueError("Fuente desconocida")
        province = resolve_provinces(body.get("provincia") or conf.criteria.get("provincias"))[0]

        def target():
            from ..diagnose import diagnose

            report, archive, results = diagnose(conf, fuentes, province, conf.output["carpeta"])
            return {"texto": report, "zip": str(archive.resolve()), "fuentes": results}

        if not jobs.start("diagnostico", target):
            return jsonify(error="Ya hay un trabajo en marcha"), 409
        return jsonify(ok=True), 202

    @app.post("/api/telegram/prueba")
    def telegram_prueba():
        from ..notify import send_text

        tg = cfg().data.get("notificaciones", {}).get("telegram", {})
        if not (tg.get("token") and tg.get("chat_id")):
            raise ValueError("Falta el token o el chat id de Telegram")
        ok = send_text("✅ CasaScan: los avisos de Telegram funcionan.", tg["token"], str(tg["chat_id"]))
        return jsonify(ok=ok), (200 if ok else 502)

    if scheduler:
        threading.Thread(target=_scheduler_loop, args=(jobs, config_path), daemon=True).start()
    return app


# ---------------------------------------------------------------- helpers
def build_meta() -> dict:
    return {
        "version": __version__,
        "modo": "servidor",
        "fuentes": [{"id": n, "nombre": c.label, "web": c.homepage} for n, c in SOURCES.items()],
        "provincias": [{"codigo": c, "nombre": n, "ccaa": CCAA_DE.get(c, "")} for c, n in PROVINCIAS.items()],
        "ccaa": list(CCAA_PROVINCIAS),
        "tipos": list(TIPOS_INMUEBLE),
        "marcas": [m for m in MARK_STATES if m],
    }


def trim(item: dict) -> dict:
    out = dict(item)
    desc = out.get("description") or ""
    if len(desc) > DESCRIPTION_MAX:
        out["description"] = desc[:DESCRIPTION_MAX] + "…"
    return out


def summarize(items: list[dict]) -> dict:
    now = datetime.now().isoformat()
    by_source: dict[str, int] = {}
    for i in items:
        by_source[i["source"]] = by_source.get(i["source"], 0) + 1
    return {
        "vigentes": len(items),
        "nuevos": sum(1 for i in items if i.get("is_new")),
        "bajadas": sum(1 for i in items if i.get("price_drop")),
        "subastas_abiertas": sum(
            1 for i in items if i.get("kind") == "subasta" and (not i.get("end_date") or i["end_date"] >= now[:10])
        ),
        "favoritos": sum(1 for i in items if i.get("marca") == "favorito"),
        "por_fuente": by_source,
    }


def editable_config(raw: dict) -> dict:
    """Vista de la configuración para la web (sin expandir variables ni mostrar secretos)."""
    full = deep_merge(DEFAULTS, raw)
    tg = full.get("notificaciones", {}).get("telegram", {})
    token = str(tg.get("token") or "")
    return {
        "criterios": full["criterios"],
        "fuentes": {
            name: {k: v for k, v in opts.items() if k in EDITABLE_SOURCE_OPTIONS}
            for name, opts in full["fuentes"].items()
        },
        "red": {k: full["red"].get(k) for k in ("pausa_min", "pausa_max", "navegador", "navegador_visible")},
        "plataforma": {"auto_horas": (full.get("plataforma") or {}).get("auto_horas", 0)},
        "enriquecer_catastro": full.get("enriquecer_catastro", True),
        "telegram": {
            "activo": tg.get("activo", "auto"),
            "token": token if token.startswith("${") else ("••••" + token[-4:] if token else ""),
            "chat_id": str(tg.get("chat_id") or ""),
        },
    }


def apply_config_changes(raw: dict, body: dict) -> dict:
    raw = json.loads(json.dumps(raw))  # copia
    if "criterios" in body:
        crit = raw.setdefault("criterios", {})
        for field, value in body["criterios"].items():
            if field in CRITERIA_TYPES:
                crit[field] = _coerce(value, CRITERIA_TYPES[field], field)
        resolve_provinces(crit.get("provincias"))  # valida
        bad = [t for t in crit.get("tipos") or [] if t not in TIPOS_INMUEBLE]
        if bad:
            raise ValueError(f"Tipo de inmueble no válido: {', '.join(bad)}")
    for name, opts in (body.get("fuentes") or {}).items():
        if name not in SOURCES:
            raise ValueError(f"Fuente desconocida: {name}")
        target = raw.setdefault("fuentes", {}).setdefault(name, {})
        for k, v in opts.items():
            if k in EDITABLE_SOURCE_OPTIONS:
                target[k] = _coerce(v, EDITABLE_SOURCE_OPTIONS[k], f"{name}.{k}")
    if "red" in body:
        red = raw.setdefault("red", {})
        for k in ("pausa_min", "pausa_max"):
            if k in body["red"]:
                red[k] = max(0.5, _coerce(body["red"][k], float, k) or 0.5)
        for k in ("navegador", "navegador_visible"):
            if k in body["red"]:
                red[k] = _coerce(body["red"][k], bool, k)
    if "plataforma" in body:
        hours = _coerce(body["plataforma"].get("auto_horas"), float, "auto_horas") or 0
        raw.setdefault("plataforma", {})["auto_horas"] = max(0.0, hours)
    if "enriquecer_catastro" in body:
        raw["enriquecer_catastro"] = _coerce(body["enriquecer_catastro"], bool, "enriquecer_catastro")
    if "telegram" in body:
        tg = raw.setdefault("notificaciones", {}).setdefault("telegram", {})
        t = body["telegram"]
        if "activo" in t:
            tg["activo"] = t["activo"] if t["activo"] in (True, False, "auto") else "auto"
        if t.get("token") and not str(t["token"]).startswith("••••"):
            tg["token"] = str(t["token"]).strip()
        if "chat_id" in t:
            tg["chat_id"] = str(t["chat_id"]).strip()
    return raw


def start_search(jobs: JobManager, config_path: str, fuentes: list[str] | None, origin: str) -> bool:
    def target():
        from ..runner import run

        result = run(Config.load(config_path), fuentes, should_stop=jobs.should_stop)
        return {
            "id": result.run_id,
            "encontrados": len(result.items),
            "nuevos": len(result.new_items),
            "errores": result.errors,
            "estadisticas": {k: list(v) for k, v in result.stats.items()},
            "interrumpida": result.interrupted,
        }

    return jobs.start("busqueda", target, origin=origin)


def next_auto_run(config: Config, last_run: dict | None) -> str | None:
    hours = float((config.data.get("plataforma") or {}).get("auto_horas") or 0)
    if hours <= 0:
        return None
    if not last_run or not last_run.get("finished"):
        return datetime.now().isoformat(timespec="seconds")
    return (datetime.fromisoformat(last_run["finished"]) + timedelta(hours=hours)).isoformat(timespec="seconds")


def _scheduler_loop(jobs: JobManager, config_path: str, interval: float = 30.0) -> None:
    """Lanza búsquedas automáticas cada `plataforma.auto_horas` horas."""
    while True:
        time.sleep(interval)
        try:
            conf = Config.load(config_path)
            st = Storage(conf.output["base_datos"])
            try:
                runs = st.runs(1)
            finally:
                st.close()
            due = next_auto_run(conf, runs[0] if runs else None)
            if due and not jobs.running and datetime.fromisoformat(due) <= datetime.now():
                log.info("Búsqueda automática programada")
                start_search(jobs, config_path, None, origin="automatica")
        except Exception as exc:  # el programador no debe morir nunca
            log.warning("Programador: %s", exc)
