"""Modo diagnóstico: comprueba cada web y guarda lo que devuelve.

Las webs cambian a menudo. Este modo hace una búsqueda mínima en cada fuente,
guarda todas las páginas recibidas y resume su estructura (qué elementos
encuentra el bot y cuáles no), para poder arreglar un extractor sin tener que
reproducir el problema. Genera una carpeta y un .zip para compartir.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from bs4 import BeautifulSoup

from .config import Config
from .http import BlockedError, HttpClient, looks_blocked
from .models import Listing
from .provinces import province_name
from .report import SOURCE_LABELS
from .sources import SOURCES
from .sources.generic import extract_listings, walk_json
from .textutil import clean

KEY_FIELDS = ("price", "surface_m2", "rooms", "city", "province_code", "property_type", "end_date")


def page_hints(text: str, url: str = "https://example.com/") -> dict[str, Any]:
    """Resumen de la estructura de una página (o JSON) recibida."""
    stripped = text.lstrip()
    if stripped[:1] in ("{", "["):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return {"tipo": "json inválido"}
        found: list[dict] = []
        walk_json(data, url, found)
        keys = list(data)[:12] if isinstance(data, dict) else f"lista de {len(data)}"
        return {"tipo": "json", "claves": keys, "anuncios_detectados": len(found)}
    soup = BeautifulSoup(text, "lxml")
    th_texts = list(dict.fromkeys(clean(th.get_text(" ")) for th in soup.select("table th")))
    dt_texts = list(dict.fromkeys(clean(dt.get_text(" ")) for dt in soup.select("dl dt")))
    hints: dict[str, Any] = {
        "tipo": "html",
        "titulo": clean(soup.title.get_text())[:90] if soup.title else "",
        "bloqueo": looks_blocked(200, text),
        "captcha": "captcha" in text.lower(),
        "li.resultado-busqueda": len(soup.select("li.resultado-busqueda")),
        "div.tablas-resultados": len(soup.select("div.tablas-resultados table")),
        "article.item": len(soup.select("article.item")),
        "article": len(soup.select("article")),
        "json_ld": len(soup.find_all("script", type="application/ld+json")),
        "__NEXT_DATA__": bool(soup.find("script", id="__NEXT_DATA__")),
        "estado_js": len(re.findall(r"__[A-Za-z0-9_]+__\s*=", text)),
        "anuncios_genericos": len(extract_listings(text, url)),
        "th": th_texts[:20],
        "dt": dt_texts[:20],
    }
    return {k: v for k, v in hints.items() if v not in (0, False, "", [], None) or k == "tipo"}


def _sample(item: Listing) -> dict[str, Any]:
    d = item.to_dict()
    keep = ("id", "url", "title", "price", "surface_m2", "rooms", "city", "province_code",
            "property_type", "status", "end_date")
    out = {k: d[k] for k in keep if d.get(k) not in (None, "")}
    out["title"] = str(out.get("title", ""))[:80]
    return out


def run_diagnostics(
    config: Config,
    names: list[str],
    province: str,
    out_dir: Path,
    http_factory: Callable[[dict], HttpClient] = HttpClient,
    max_items: int = 3,
) -> list[dict]:
    results = []
    for name in names:
        net = {**config.net, "reintentos": 1, "guardar_paginas": str(out_dir / name)}
        http = http_factory(net)
        options = {**config.source(name), "limite": 2, "max_paginas": 1, "cache_horas": 0, "dias": 2}
        source = SOURCES[name](http, options, config.criteria)
        items: list[Listing] = []
        error = ""
        start = time.monotonic()
        try:
            for item in source.search([province]):
                items.append(item)
                if len(items) >= max_items:
                    break
        except BlockedError as exc:
            error = f"BLOQUEO: {exc}"
        except Exception as exc:  # se informa, no se para
            error = f"{type(exc).__name__}: {exc}"
        finally:
            http.close()
        requests_info = []
        for entry in http.trace:
            info = dict(entry)
            if entry.get("file"):
                text = (out_dir / name / entry["file"]).read_text(encoding="utf-8", errors="replace")
                info["pistas"] = page_hints(text, entry["url"])
            requests_info.append(info)
        missing = [f for f in KEY_FIELDS if items and all(getattr(i, f) in (None, "") for i in items)]
        results.append(
            {
                "fuente": name,
                "provincia": province,
                "segundos": round(time.monotonic() - start, 1),
                "error": error,
                "resultados": len(items),
                "campos_vacios": missing,
                "muestra": [_sample(i) for i in items],
                "peticiones": requests_info,
            }
        )
    return results


def _short_url(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url)[:90]


def format_report(results: list[dict]) -> str:
    lines = []
    for r in results:
        label = SOURCE_LABELS.get(r["fuente"], r["fuente"])
        if r["error"]:
            state = f"✗ {r['error'][:160]}"
        elif r["resultados"]:
            state = f"✓ {r['resultados']} resultados"
        else:
            state = "⚠ 0 resultados (la web respondió pero no se ha extraído nada)"
        lines.append(f"\n■ {label} [{r['fuente']}] · {province_name(r['provincia'])} · {r['segundos']} s\n  {state}")
        if r["campos_vacios"]:
            lines.append(f"  campos sin extraer en todos los resultados: {', '.join(r['campos_vacios'])}")
        shown_th: set[str] = set()
        for p in r["peticiones"][:8]:
            line = f"  {p['method']:<7} {p['status']:>3} {p['bytes'] // 1024:>4} KB  {_short_url(p['url'])}"
            if p.get("error"):
                line += f"  → {p['error'][:120]}"
            hints = p.get("pistas") or {}
            compact = {k: v for k, v in hints.items() if k not in ("tipo", "th", "dt", "titulo")}
            if compact:
                line += "\n            " + " · ".join(f"{k}={v}" for k, v in compact.items())
            for key in ("th", "dt"):
                labels = hints.get(key)
                sig = f"{key}:{labels}"
                if labels and sig not in shown_th:
                    shown_th.add(sig)
                    line += f"\n            {key}: {' | '.join(labels[:14])}"
            lines.append(line)
        if len(r["peticiones"]) > 8:
            lines.append(f"  … {len(r['peticiones']) - 8} peticiones más (ver diagnostico.json)")
        for s in r["muestra"][:2]:
            lines.append("  ejemplo: " + json.dumps(s, ensure_ascii=False)[:300])
    return "\n".join(lines)


def diagnose(config: Config, names: list[str], province: str, base_folder: str) -> tuple[str, Path, list[dict]]:
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out_dir = Path(base_folder) / f"diagnostico_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = run_diagnostics(config, names, province, out_dir)
    (out_dir / "diagnostico.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    report = format_report(results)
    (out_dir / "diagnostico.txt").write_text(report, encoding="utf-8")
    archive = Path(shutil.make_archive(str(out_dir), "zip", root_dir=out_dir))
    return report, archive, results
