"""Línea de comandos de CasaScan.

Ejemplos:
    python -m casascan buscar
    python -m casascan buscar --provincias Malaga,Cadiz --precio-max 120000 --fuentes boe,seguridad_social
    python -m casascan vigilar --cada 360
    python -m casascan fuentes
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
import webbrowser
from pathlib import Path

from .config import Config
from .provinces import CCAA_PROVINCIAS, PROVINCIAS
from .runner import run
from .sources import SOURCES

EXAMPLE_CONFIG = Path(__file__).resolve().parent.parent / "config.example.yaml"


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="casascan",
        description="Bot que recorre portales inmobiliarios, bancos/Sareb y subastas oficiales "
        "y te saca lo que cumple tus criterios.",
    )
    sub = p.add_subparsers(dest="cmd")

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("-c", "--config", default="config.yaml", help="fichero de configuración (config.yaml)")
        sp.add_argument("--fuentes", type=_csv, help=f"solo estas fuentes: {','.join(SOURCES)}")
        sp.add_argument("--provincias", type=_csv, help="códigos INE, nombres o comunidades (coma)")
        sp.add_argument("--localidades", type=_csv, help="filtra por localidades (coma)")
        sp.add_argument("--tipos", type=_csv, help="vivienda,local,garaje,trastero,nave,solar,rustica")
        sp.add_argument("--precio-max", type=float)
        sp.add_argument("--precio-min", type=float)
        sp.add_argument("--m2-min", type=float)
        sp.add_argument("--habitaciones-min", type=int)
        sp.add_argument("--limite", type=int, help="máximo de resultados por provincia y fuente (para probar)")
        sp.add_argument("--sin-detalle", action="store_true", help="no abrir la ficha de cada subasta (más rápido)")
        sp.add_argument("--navegador", action="store_true", help="usar Chromium real (Playwright) para webs con anti-bot")
        sp.add_argument("--navegador-visible", action="store_true", help="como --navegador pero con ventana visible")
        sp.add_argument("--solo-nuevos", action="store_true", help="el informe solo incluye novedades")
        sp.add_argument("--abrir", action="store_true", help="abrir el informe en el navegador al terminar")
        sp.add_argument("-v", "--verbose", action="store_true")

    common(sub.add_parser("buscar", help="ejecuta una búsqueda en todas las fuentes"))
    w = sub.add_parser("vigilar", help="repite la búsqueda cada X minutos y avisa de novedades")
    common(w)
    w.add_argument("--cada", type=float, default=360, help="minutos entre búsquedas (por defecto 360)")
    d = sub.add_parser("diagnostico", help="prueba cada web, guarda lo que devuelve y resume qué falla")
    d.add_argument("-c", "--config", default="config.yaml")
    d.add_argument("--fuentes", type=_csv, help=f"solo estas fuentes: {','.join(SOURCES)}")
    d.add_argument("--provincias", type=_csv, help="provincia de prueba (se usa la primera)")
    d.add_argument("--navegador", action="store_true")
    d.add_argument("--navegador-visible", action="store_true")
    d.add_argument("-v", "--verbose", action="store_true")
    web = sub.add_parser("web", help="abre la plataforma web (http://127.0.0.1:8000)")
    web.add_argument("-c", "--config", default="config.yaml")
    web.add_argument("--host", default="127.0.0.1", help="0.0.0.0 para entrar desde otros equipos (pide contraseña)")
    web.add_argument("--puerto", type=int, default=8000)
    web.add_argument("--no-abrir", action="store_true", help="no abrir el navegador")
    web.add_argument("--sin-clave", action="store_true",
                     help="permitir acceso desde otros equipos sin contraseña (no recomendado)")
    web.add_argument("-v", "--verbose", action="store_true")
    ex = sub.add_parser("exportar-web", help="genera la web estática de solo lectura (GitHub Pages)")
    ex.add_argument("-c", "--config", default="config.yaml")
    ex.add_argument("--salida", default="web_publica")
    sub.add_parser("fuentes", help="lista las fuentes disponibles")
    sub.add_parser("provincias", help="lista provincias y comunidades con su código")
    i = sub.add_parser("init", help="crea config.yaml a partir del ejemplo")
    i.add_argument("-c", "--config", default="config.yaml")
    return p


def apply_overrides(cfg: Config, args: argparse.Namespace) -> None:
    c = cfg.criteria
    if args.provincias:
        c["provincias"] = args.provincias
    if args.localidades:
        c["localidades"] = args.localidades
    if args.tipos:
        c["tipos"] = args.tipos
    for arg, key in (("precio_max", "precio_max"), ("precio_min", "precio_min"),
                     ("m2_min", "superficie_min"), ("habitaciones_min", "habitaciones_min")):
        if getattr(args, arg) is not None:
            c[key] = getattr(args, arg)
    if args.sin_detalle:
        for name in ("boe", "seguridad_social"):
            cfg.source(name)["detalle"] = False
    if args.navegador or args.navegador_visible:
        cfg.net["navegador"] = True
        cfg.net["navegador_visible"] = bool(args.navegador_visible)
    if args.solo_nuevos:
        cfg.output["solo_nuevos"] = True


def _eur(v) -> str:
    return f"{v:,.0f} €".replace(",", ".") if v else "—"


def print_summary(result) -> None:
    print("\nResumen por fuente:")
    for name, (seen, kept) in result.stats.items():
        label = SOURCES[name].label
        err = f"  ⚠ {result.errors[name]}" if name in result.errors else ""
        print(f"  {label:<55} vistos {seen:>4} · cumplen {kept:>4}{err}")
    news = result.new_items
    print(f"\nTotal: {len(result.items)} resultados ({len(news)} nuevos o con bajada de precio)")
    for it in news[:25]:
        extra = " · ".join(x for x in (
            f"{it.surface_m2:.0f} m²" if it.surface_m2 else "",
            f"{it.rooms} hab" if it.rooms else "",
            it.city or it.province,
        ) if x)
        print(f"  [{it.source}] {_eur(it.price):>12}  {extra}\n      {it.url}")
    if len(news) > 25:
        print(f"  … y {len(news) - 25} más en el informe")
    if result.files:
        html = next((f for f in result.files if f.name == "ultimo.html"), result.files[0])
        print(f"\nInforme: {html.resolve()}")


def run_web(args: argparse.Namespace) -> int:
    import os
    import threading

    from .web import create_app

    password = os.environ.get("CASASCAN_PASSWORD", "")
    local = args.host in ("127.0.0.1", "localhost", "::1")
    if not local and not password and not args.sin_clave:
        print(
            "Para abrir la plataforma a otros equipos define una contraseña en la variable "
            "CASASCAN_PASSWORD (o usa --sin-clave bajo tu responsabilidad).",
            file=sys.stderr,
        )
        return 2
    app = create_app(args.config, password=password, allow_any_host=bool(args.sin_clave))
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.puerto}/"
    print(f"CasaScan está en {url}  (Ctrl+C para cerrar)")
    if not args.no_abrir:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        from waitress import serve  # type: ignore
    except ImportError:
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
        app.run(host=args.host, port=args.puerto, threaded=True, use_reloader=False)
    else:
        serve(app, host=args.host, port=args.puerto, threads=8)
    return 0


def run_diagnostico(args: argparse.Namespace) -> int:
    from .diagnose import diagnose
    from .provinces import resolve_provinces

    cfg = Config.load(args.config)
    if args.navegador or args.navegador_visible:
        cfg.net["navegador"] = True
        cfg.net["navegador_visible"] = bool(args.navegador_visible)
    try:
        province = resolve_provinces(args.provincias or cfg.criteria.get("provincias"))[0]
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    names = args.fuentes or cfg.enabled_sources()
    unknown = [n for n in names if n not in SOURCES]
    if unknown:
        print(f"Error: fuentes desconocidas: {', '.join(unknown)}", file=sys.stderr)
        return 2
    print(f"Diagnóstico de {len(names)} fuentes en la provincia {province} (unos minutos)…")
    report, archive, _ = diagnose(cfg, names, province, cfg.output["carpeta"])
    print(report)
    print(f"\nTodo guardado en {archive.resolve()}\n"
          "Si algo falla, comparte ese .zip (o el texto de arriba) para poder arreglarlo.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd is None:
        args = parser.parse_args(["buscar", *(argv if argv is not None else sys.argv[1:])])

    if args.cmd == "fuentes":
        for name, cls in SOURCES.items():
            print(f"  {name:<18} {cls.label}  ({cls.homepage})")
        return 0
    if args.cmd == "provincias":
        for code, name in PROVINCIAS.items():
            print(f"  {code}  {name}")
        print("\nComunidades (también valen en 'provincias'):", ", ".join(CCAA_PROVINCIAS))
        return 0
    if args.cmd == "init":
        if Path(args.config).exists():
            print(f"{args.config} ya existe; no lo sobrescribo.")
            return 1
        if EXAMPLE_CONFIG.exists():
            shutil.copy(EXAMPLE_CONFIG, args.config)
        else:  # instalado como paquete: se escriben los valores por defecto
            import yaml

            from .config import DEFAULTS

            Path(args.config).write_text(yaml.safe_dump(DEFAULTS, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(f"Creado {args.config}. Edita tus criterios y ejecuta: python -m casascan buscar")
        return 0

    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("urllib3", "charset_normalizer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if not Path(args.config).exists():
        logging.getLogger("casascan").warning(
            "No existe %s: uso los valores por defecto (crea uno con: python -m casascan init)", args.config
        )

    if args.cmd == "diagnostico":
        return run_diagnostico(args)
    if args.cmd == "web":
        return run_web(args)
    if args.cmd == "exportar-web":
        from .web.export import export_static

        out = export_static(Config.load(args.config), args.salida)
        print(f"Web estática generada en {out.resolve()} (ábrela con un servidor web o súbela a GitHub Pages)")
        return 0

    while True:
        cfg = Config.load(args.config)
        apply_overrides(cfg, args)
        try:
            result = run(cfg, args.fuentes, args.limite)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        print_summary(result)
        if args.abrir and args.cmd == "buscar":
            report = next((f for f in result.files if f.name == "ultimo.html"), None)
            if report:
                webbrowser.open(report.resolve().as_uri())
        if args.cmd != "vigilar" or result.interrupted:
            return 0 if not result.errors else 1
        print(f"\nPróxima búsqueda en {args.cada:.0f} minutos (Ctrl+C para salir)…")
        try:
            time.sleep(args.cada * 60)
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    sys.exit(main())
