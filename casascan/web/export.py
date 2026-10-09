"""Exporta la plataforma como web estática de solo lectura (para GitHub Pages).

La versión estática muestra lo encontrado en la última búsqueda, con los mismos
filtros, pero sin lanzar búsquedas ni editar criterios. Las marcas y notas
privadas NO se exportan; en la web estática los favoritos se guardan solo en el
navegador de quien la visita.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from ..config import Config
from ..storage import Storage
from .app import STATIC, build_meta, summarize, trim

PRIVATE_FIELDS = ("marca", "nota")


def export_static(config: Config, out_dir: str) -> Path:
    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(STATIC, out / "static", ignore=shutil.ignore_patterns("index.html"))
    shutil.copy(STATIC / "index.html", out / "index.html")
    st = Storage(config.output["base_datos"])
    try:
        items = [i for i in st.listings() if i["vigente"]]
        runs = st.runs(20)
    finally:
        st.close()
    for i in items:
        for f in PRIVATE_FIELDS:
            i.pop(f, None)
    resumen = summarize(items)
    resumen["ultima_busqueda"] = runs[0] if runs else None
    data = {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "meta": {**build_meta(), "modo": "estatico"},
        "resumen": resumen,
        "inmuebles": [trim(i) for i in items],
        "historial": runs,
    }
    (out / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return out
