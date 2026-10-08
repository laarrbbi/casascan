"""Informes: CSV (abre en Excel), JSON y HTML con tabla filtrable."""

from __future__ import annotations

import csv
import html
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from .models import Listing

COLUMNS = [
    ("nuevo", lambda x: "SÍ" if x.is_new else ""),
    ("bajada_precio", lambda x: "SÍ" if x.price_drop else ""),
    ("fuente", lambda x: x.source),
    ("tipo", lambda x: x.kind),
    ("inmueble", lambda x: x.property_type),
    ("titulo", lambda x: x.title),
    ("precio", lambda x: x.price),
    ("precio_anterior", lambda x: x.previous_price),
    ("tasacion", lambda x: x.appraisal),
    ("valor_subasta", lambda x: x.auction_value),
    ("puja_minima", lambda x: x.min_bid),
    ("deposito", lambda x: x.deposit),
    ("descuento_%", lambda x: x.discount_pct),
    ("superficie_m2", lambda x: x.surface_m2),
    ("eur_m2", lambda x: x.price_per_m2),
    ("habitaciones", lambda x: x.rooms),
    ("banos", lambda x: x.bathrooms),
    ("direccion", lambda x: x.address),
    ("cp", lambda x: x.postal_code),
    ("localidad", lambda x: x.city),
    ("provincia", lambda x: x.province),
    ("ref_catastral", lambda x: x.cadastral_ref),
    ("estado", lambda x: x.status),
    ("inicio", lambda x: x.start_date),
    ("fin", lambda x: x.end_date),
    ("vendedor", lambda x: x.seller),
    ("url", lambda x: x.url),
    ("catastro", lambda x: catastro_url(x.cadastral_ref)),
    ("descripcion", lambda x: x.description[:1000]),
    ("visto_por_primera_vez", lambda x: x.first_seen),
    ("extra", lambda x: json.dumps(x.extra, ensure_ascii=False) if x.extra else ""),
]

SOURCE_LABELS = {
    "idealista": "Idealista",
    "fotocasa": "Fotocasa",
    "aliseda": "Aliseda (Sareb)",
    "servihabitat": "Servihabitat",
    "boe": "Subastas BOE",
    "seguridad_social": "Seguridad Social",
    "boe_anuncios": "BOE pre-subasta",
}


def catastro_url(ref: str) -> str:
    if not ref or len(ref) < 14:
        return ""
    return f"https://www1.sedecatastro.gob.es/CYCBienInmueble/OVCListaBienes.aspx?rc1={ref[:7]}&rc2={ref[7:14]}"


def maps_url(item: Listing) -> str:
    if item.lat and item.lon:
        return f"https://www.google.com/maps/search/?api=1&query={item.lat},{item.lon}"
    q = ", ".join(x for x in (item.address, item.postal_code, item.city, item.province) if x)
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(q)}" if q else ""


def write_csv(items: list[Listing], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:  # utf-8-sig: Excel lee bien las tildes
        w = csv.writer(fh, delimiter=";")
        w.writerow([c for c, _ in COLUMNS])
        for it in items:
            w.writerow(["" if (v := f(it)) is None else v for _, f in COLUMNS])


def write_json(items: list[Listing], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([it.to_dict() for it in items], fh, ensure_ascii=False, indent=2)


def _eur(v) -> str:
    if v is None:
        return ""
    return f"{v:,.0f} €".replace(",", ".")


def write_html(items: list[Listing], path: Path, errors: dict[str, str] | None = None, title: str = "") -> None:
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    counts = Counter(it.source for it in items)
    new = sum(1 for it in items if it.is_new)
    rows = []
    for it in items:
        badges = ""
        if it.is_new:
            badges += '<span class="b new">NUEVO</span>'
        if it.price_drop:
            badges += f'<span class="b drop">BAJA {_eur(it.previous_price)} → {_eur(it.price)}</span>'
        links = [f'<a href="{html.escape(it.url)}" target="_blank" rel="noopener">ver</a>']
        if (m := maps_url(it)):
            links.append(f'<a href="{html.escape(m)}" target="_blank" rel="noopener">mapa</a>')
        if (c := catastro_url(it.cadastral_ref)):
            links.append(f'<a href="{html.escape(c)}" target="_blank" rel="noopener">catastro</a>')
        econ = []
        if it.appraisal:
            econ.append(f"tasación {_eur(it.appraisal)}")
        if it.min_bid:
            econ.append(f"puja mín. {_eur(it.min_bid)}")
        if it.deposit:
            econ.append(f"depósito {_eur(it.deposit)}")
        if it.discount_pct is not None:
            econ.append(f"{it.discount_pct:.0f}% bajo tasación")
        sub = " · ".join(econ)
        fin = it.end_date[:16].replace("T", " ") if it.end_date else ""
        if not fin and it.start_date:
            fin = f"publicado {it.start_date[:10]}"
        rows.append(
            f'<tr data-src="{it.source}" data-new="{int(it.is_new)}">'
            f'<td>{badges}<span class="src">{SOURCE_LABELS.get(it.source, it.source)}</span></td>'
            f"<td><b>{html.escape(it.title or it.address or it.id)}</b>"
            f'<div class="muted">{html.escape(it.description[:220])}</div></td>'
            f'<td class="num" data-v="{it.price or 0}">{_eur(it.price)}<div class="muted">{sub}</div></td>'
            f'<td class="num" data-v="{it.surface_m2 or 0}">{f"{it.surface_m2:.0f} m²" if it.surface_m2 else ""}</td>'
            f'<td class="num" data-v="{it.price_per_m2 or 0}">{_eur(it.price_per_m2)}</td>'
            f'<td class="num" data-v="{it.rooms or 0}">{it.rooms or ""}</td>'
            f"<td>{html.escape(', '.join(x for x in (it.city, it.province) if x))}</td>"
            f"<td>{html.escape(it.status)}<div class='muted'>{fin}</div></td>"
            f"<td>{' · '.join(links)}</td></tr>"
        )
    err_html = ""
    if errors:
        err_html = "<div class='err'><b>Fuentes con problemas:</b><ul>" + "".join(
            f"<li><b>{html.escape(SOURCE_LABELS.get(k, k))}</b>: {html.escape(v)}</li>" for k, v in errors.items()
        ) + "</ul></div>"
    chips = "".join(
        f'<button class="chip" data-f="{s}">{SOURCE_LABELS.get(s, s)} <b>{n}</b></button>' for s, n in counts.items()
    )
    page = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CasaScan · {html.escape(title or "resultados")}</title>
<style>
:root {{ --bg:#f7f7f5; --fg:#1d1d1b; --muted:#6b6b66; --card:#fff; --line:#e3e3de; --acc:#0b6e4f; --warn:#b54708; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141413; --fg:#ececea; --muted:#9a9a94; --card:#1e1e1c; --line:#33332f; --acc:#3fb68b; --warn:#f0a050; }} }}
body {{ margin:0; font:14px/1.45 system-ui, -apple-system, Segoe UI, sans-serif; background:var(--bg); color:var(--fg); }}
header {{ padding:20px 16px 8px; }} h1 {{ margin:0 0 4px; font-size:22px; }}
.muted {{ color:var(--muted); font-size:12px; }}
.bar {{ display:flex; flex-wrap:wrap; gap:8px; padding:8px 16px; align-items:center; }}
.chip {{ border:1px solid var(--line); background:var(--card); color:var(--fg); border-radius:99px; padding:4px 10px; cursor:pointer; }}
.chip.on {{ border-color:var(--acc); color:var(--acc); }}
input {{ padding:6px 10px; border:1px solid var(--line); border-radius:6px; background:var(--card); color:var(--fg); min-width:220px; }}
.wrap {{ overflow-x:auto; padding:0 16px 24px; }}
table {{ border-collapse:collapse; width:100%; background:var(--card); border:1px solid var(--line); }}
th, td {{ padding:8px; border-bottom:1px solid var(--line); vertical-align:top; text-align:left; }}
th {{ cursor:pointer; position:sticky; top:0; background:var(--card); white-space:nowrap; }}
.num {{ text-align:right; white-space:nowrap; }}
.b {{ display:inline-block; font-size:11px; font-weight:600; border-radius:4px; padding:1px 6px; margin:0 4px 4px 0; color:#fff; }}
.b.new {{ background:var(--acc); }} .b.drop {{ background:var(--warn); }}
.src {{ display:block; font-size:12px; color:var(--muted); }}
.err {{ margin:8px 16px; padding:10px 14px; border:1px solid var(--warn); border-radius:6px; }}
a {{ color:var(--acc); }}
</style></head><body>
<header><h1>CasaScan</h1>
<div class="muted">{len(items)} resultados que cumplen tus criterios · {new} nuevos · generado el {now}</div></header>
{err_html}
<div class="bar"><input id="q" placeholder="Filtrar por texto (localidad, calle…)">
<button class="chip" data-f="new">Solo nuevos</button>{chips}</div>
<div class="wrap"><table id="t"><thead><tr>
<th>Fuente</th><th>Inmueble</th><th>Precio</th><th>m²</th><th>€/m²</th><th>Hab.</th><th>Ubicación</th><th>Estado / fin</th><th>Enlaces</th>
</tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<script>
const rows=[...document.querySelectorAll('#t tbody tr')];let src=null,onlyNew=false;
function apply(){{const q=document.getElementById('q').value.toLowerCase();
rows.forEach(r=>{{const ok=(!src||r.dataset.src===src)&&(!onlyNew||r.dataset.new==='1')&&r.textContent.toLowerCase().includes(q);r.style.display=ok?'':'none';}});}}
document.getElementById('q').addEventListener('input',apply);
document.querySelectorAll('.chip').forEach(b=>b.addEventListener('click',()=>{{
 if(b.dataset.f==='new'){{onlyNew=!onlyNew;b.classList.toggle('on',onlyNew);}}
 else{{src=src===b.dataset.f?null:b.dataset.f;document.querySelectorAll('.chip[data-f]:not([data-f=new])').forEach(c=>c.classList.toggle('on',c.dataset.f===src));}}
 apply();}}));
document.querySelectorAll('#t th').forEach((th,i)=>th.addEventListener('click',()=>{{
 const tb=th.closest('table').tBodies[0];const asc=th.dataset.asc!=='1';th.dataset.asc=asc?'1':'0';
 const val=r=>{{const c=r.cells[i];return c.dataset.v!==undefined?parseFloat(c.dataset.v):c.textContent.trim().toLowerCase();}};
 [...tb.rows].sort((a,b)=>{{const x=val(a),y=val(b);return (x>y?1:x<y?-1:0)*(asc?1:-1);}}).forEach(r=>tb.appendChild(r));}}));
</script></body></html>"""
    path.write_text(page, encoding="utf-8")


def write_reports(items: list[Listing], folder: str, formats: list[str], errors: dict[str, str] | None = None) -> list[Path]:
    out_dir = Path(folder)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    written: list[Path] = []
    for fmt in formats:
        for name in (f"casascan_{stamp}.{fmt}", f"ultimo.{fmt}"):
            p = out_dir / name
            if fmt == "csv":
                write_csv(items, p)
            elif fmt == "json":
                write_json(items, p)
            elif fmt == "html":
                write_html(items, p, errors, title=stamp)
            else:
                continue
            written.append(p)
    return written
