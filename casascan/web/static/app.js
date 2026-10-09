/* CasaScan · plataforma web.
   Funciona en dos modos:
   - "servidor": servida por `python -m casascan web`, con API para buscar, editar criterios y marcar.
   - "estatico": versión publicada (GitHub Pages) que lee data.json; solo lectura, las marcas
     se guardan en este navegador. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

const SOURCE_SHORT = {
  boe: "Subastas BOE", seguridad_social: "Seguridad Social", idealista: "Idealista", fotocasa: "Fotocasa",
  aliseda: "Aliseda · Sareb", servihabitat: "Servihabitat", boe_anuncios: "BOE pre-subasta",
};
const KIND = { venta: "En venta", subasta: "Subasta", anuncio: "Pre-subasta" };
const TYPE_LABEL = {
  vivienda: "Vivienda", local: "Local", garaje: "Garaje", trastero: "Trastero", nave: "Nave",
  solar: "Solar", rustica: "Finca rústica", edificio: "Edificio", otro: "Otro inmueble",
};
const MARKS = { favorito: "Favorito", contactado: "Contactado", visitado: "Visitado", descartado: "Descartado" };
const BOE_STATES = { PU: "Próxima apertura", EJ: "Celebrándose", SU: "Suspendida" };
const ORIGINS = { judicial: "Juzgados", notarial: "Notarías", agencia_tributaria: "Agencia Tributaria", administrativa: "Otras administraciones" };
const URL_SOURCES = ["idealista", "fotocasa", "aliseda", "servihabitat"];
const PAGE = 40;
const DEFAULT_FILTERS = {
  q: "", kind: "", sources: [], prov: "", type: "", pmin: "", pmax: "", m2: "", rooms: "", disc: "",
  onlyNew: false, onlyDrop: false, hideDiscarded: true, includeOld: false, sort: "recientes",
};

const state = {
  mode: "servidor", meta: null, items: [], config: null, job: null, logSince: 0, history: [],
  generated: null, shown: PAGE, view: "resultados", track: "", filters: { ...DEFAULT_FILTERS }, openNotes: new Set(),
  lastRun: null, nextRun: null,
};

/* ───────── utilidades ───────── */
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "");
const norm = (s) => String(s ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
// useGrouping "always": en España se escribe 4.997 €, no 4997 €
const eurFmt = new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR", maximumFractionDigits: 0, useGrouping: "always" });
const numFmt = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 0, useGrouping: "always" });
const eur = (v) => (v == null || v === "" ? "" : eurFmt.format(v));
const num = (v) => (v == null || v === "" ? "" : numFmt.format(v));
const has = (v) => v !== null && v !== undefined && v !== "";

function fmtDate(iso, time = false) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const opts = { day: "numeric", month: "short", year: "numeric" };
  if (time) Object.assign(opts, { hour: "2-digit", minute: "2-digit" });
  return d.toLocaleString("es-ES", opts);
}
function ago(iso) {
  if (!iso) return "";
  const mins = Math.round((Date.now() - new Date(iso)) / 60000);
  if (mins < 1) return "ahora mismo";
  if (mins < 60) return `hace ${mins} min`;
  const h = Math.round(mins / 60);
  if (h < 48) return `hace ${h} h`;
  return `hace ${Math.round(h / 24)} días`;
}
function daysLeft(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d)) return null;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const end = new Date(d); end.setHours(0, 0, 0, 0);
  return Math.round((end - today) / 864e5);
}
const store = {
  get(k, d) { try { const v = localStorage.getItem("casascan:" + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("casascan:" + k, JSON.stringify(v)); } catch { /* sin almacenamiento */ } },
};
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 3800);
}
async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: { Accept: "application/json" } };
  if (opts.body !== undefined || init.method !== "GET") {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body || {});
  }
  const res = await fetch(path, init);
  let data = null;
  try { data = await res.json(); } catch { /* sin cuerpo */ }
  if (!res.ok) throw new Error((data && data.error) || `Error ${res.status}`);
  return data;
}
const sourceName = (id) => SOURCE_SHORT[id] || (state.meta?.fuentes.find((f) => f.id === id)?.nombre ?? id);
const provName = (code) => state.meta?.provincias.find((p) => p.codigo === code)?.nombre ?? code;
const isServer = () => state.mode === "servidor";

/* ───────── iconos ───────── */
const ICON = {
  star: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  note: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M4 20h4L19 9l-4-4L4 16v4z"/><path d="M13.5 6.5l4 4"/></svg>',
};

/* ───────── datos ───────── */
async function loadItems() {
  state.items = await api("api/inmuebles");
  indexItems();
}
function indexItems() {
  for (const it of state.items) {
    it._hay = norm([it.title, it.address, it.city, it.province, it.postal_code, it.description, it.id,
      it.cadastral_ref, it.seller, it.extra?.expediente].join(" "));
  }
}
async function loadConfig() { state.config = await api("api/config"); }
async function loadHistory() { state.history = await api("api/historial"); }
async function loadSummary() {
  const s = await api("api/resumen");
  state.lastRun = s.ultima_busqueda; state.nextRun = s.proxima_busqueda;
  if (s.trabajo && s.trabajo.estado === "en_curso" && !jobRunning()) {
    state.job = s.trabajo; state.logSince = 0; pollJob();
  }
}
const jobRunning = () => state.job && state.job.estado === "en_curso";

/* Marcas en modo estático: solo en este navegador */
function applyLocalMarks() {
  const marks = store.get("marcas", {});
  for (const it of state.items) { it.marca = marks[it.key]?.marca || ""; it.nota = marks[it.key]?.nota || ""; }
}

/* ───────── filtros ───────── */
function computeFiltered() {
  const f = state.filters;
  const q = norm(f.q).trim();
  const list = state.items.filter((it) => {
    if (!f.includeOld && !it.vigente) return false;
    if (f.hideDiscarded && it.marca === "descartado") return false;
    if (f.kind && it.kind !== f.kind) return false;
    if (f.sources.length && !f.sources.includes(it.source)) return false;
    if (f.prov && it.province_code !== f.prov) return false;
    if (f.type && it.property_type !== f.type) return false;
    if (f.pmin && !(it.price >= +f.pmin)) return false;
    if (f.pmax && !(has(it.price) && it.price <= +f.pmax)) return false;
    if (f.m2 && !(it.surface_m2 >= +f.m2)) return false;
    if (f.rooms && !(it.rooms >= +f.rooms)) return false;
    if (f.disc && !(it.discount_pct >= +f.disc)) return false;
    if (f.onlyNew && !it.is_new) return false;
    if (f.onlyDrop && !it.price_drop) return false;
    if (q && !q.split(/\s+/).every((w) => it._hay.includes(w))) return false;
    return true;
  });
  return sortItems(list, f.sort);
}
function sortItems(list, sort) {
  const last = (v, asc = true) => (has(v) ? v : asc ? Infinity : -Infinity);
  const cmp = {
    recientes: (a, b) => (b.first_seen || "").localeCompare(a.first_seen || "") || last(a.price) - last(b.price),
    precio: (a, b) => last(a.price) - last(b.price),
    eurm2: (a, b) => last(a.price_per_m2) - last(b.price_per_m2),
    descuento: (a, b) => last(b.discount_pct, false) - last(a.discount_pct, false),
    cierre: (a, b) => {
      const da = a.kind === "subasta" ? daysLeft(a.end_date) : null;
      const db = b.kind === "subasta" ? daysLeft(b.end_date) : null;
      return last(da != null && da >= 0 ? da : null) - last(db != null && db >= 0 ? db : null);
    },
  }[sort] || (() => 0);
  return list.sort(cmp);
}
function saveFilters() { store.set("filtros", state.filters); }
function restoreFilters() { state.filters = { ...DEFAULT_FILTERS, ...store.get("filtros", {}) }; }

function buildFilterControls() {
  $("#f-kind").innerHTML = [["", "Todo"], ["venta", "En venta"], ["subasta", "Subastas"], ["anuncio", "Pre-subasta"]]
    .map(([v, l]) => `<button type="button" data-v="${v}" aria-pressed="${state.filters.kind === v}">${l}</button>`).join("");
  const present = (key) => [...new Set(state.items.map((i) => i[key]).filter(Boolean))];
  const srcs = state.meta.fuentes.map((s) => s.id).filter((id) => present("source").includes(id) || state.filters.sources.includes(id));
  $("#f-source").innerHTML = srcs.length
    ? srcs.map((id) => `<button type="button" class="chip" data-v="${id}" aria-pressed="${state.filters.sources.includes(id)}">${esc(sourceName(id))}</button>`).join("")
    : '<span class="muted small">Sin resultados todavía</span>';
  const provs = present("province_code").sort((a, b) => provName(a).localeCompare(provName(b), "es"));
  $("#f-prov").innerHTML = '<option value="">Todas</option>' + provs.map((c) => `<option value="${esc(c)}">${esc(provName(c))}</option>`).join("");
  const types = present("property_type");
  $("#f-type").innerHTML = '<option value="">Todos</option>' + types.map((t) => `<option value="${esc(t)}">${esc(TYPE_LABEL[t] || t)}</option>`).join("");
  const f = state.filters;
  $("#f-q").value = f.q; $("#f-prov").value = f.prov; $("#f-type").value = f.type;
  $("#f-pmin").value = f.pmin; $("#f-pmax").value = f.pmax; $("#f-m2").value = f.m2; $("#f-rooms").value = f.rooms;
  $("#f-disc").value = f.disc; $("#f-new").checked = f.onlyNew; $("#f-drop").checked = f.onlyDrop;
  $("#f-hide-discarded").checked = f.hideDiscarded; $("#f-old").checked = f.includeOld; $("#f-sort").value = f.sort;
}

/* ───────── fichas ───────── */
function titleOf(it) {
  const type = TYPE_LABEL[it.property_type] || "Inmueble";
  const place = it.city || it.province || "";
  if (it.kind === "subasta") return place ? `${type} en ${titleCase(place)}` : type;
  if (it.kind === "anuncio") return it.title;
  return it.title || (place ? `${type} en ${place}` : type);
}
function titleCase(s) {
  return s === s.toUpperCase() ? s.toLowerCase().replace(/(^|[\s(/-])(\p{L})/gu, (m, a, b) => a + b.toUpperCase()) : s;
}
function catastroUrl(rc) {
  return rc && rc.length >= 14 ? `https://www1.sedecatastro.gob.es/CYCBienInmueble/OVCListaBienes.aspx?rc1=${rc.slice(0, 7)}&rc2=${rc.slice(7, 14)}` : "";
}
function mapsUrl(it) {
  if (has(it.lat) && has(it.lon)) return `https://www.google.com/maps/search/?api=1&query=${it.lat},${it.lon}`;
  const q = [it.address, it.postal_code, it.city, it.province].filter(Boolean).join(", ");
  return q && it.kind !== "anuncio" ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(q)}` : "";
}

function ficha(it, { tracking = false } = {}) {
  const tags = [`<span class="tag tag-source">${esc(sourceName(it.source))}</span>`, `<span class="tag tag-${esc(it.kind)}">${esc(KIND[it.kind] || it.kind)}</span>`];
  if (it.is_new) tags.push('<span class="tag tag-new">Nuevo</span>');
  if (it.price_drop && it.previous_price) {
    const p = Math.round(100 * (1 - it.price / it.previous_price));
    tags.push(`<span class="tag tag-drop">Baja ${p}%</span>`);
  }
  if (it.kind === "subasta") {
    const d = daysLeft(it.end_date);
    if (d != null && d >= 0 && d <= 7) tags.push(`<span class="tag tag-soon">${d === 0 ? "Cierra hoy" : `Cierra en ${d} día${d > 1 ? "s" : ""}`}</span>`);
    else if (d != null && d < 0) tags.push('<span class="tag tag-old">Cerrada</span>');
  }
  if (!it.vigente) tags.push('<span class="tag tag-old">Ya no aparece</span>');
  const ref = it.kind === "anuncio" || it.kind === "subasta" ? it.id : it.cadastral_ref || "";

  const place = [it.address, [it.postal_code, it.city && titleCase(it.city)].filter(Boolean).join(" "), it.province]
    .filter(Boolean).join(" · ");
  const facts = [
    has(it.surface_m2) && `<span><b>${num(it.surface_m2)}</b> m²</span>`,
    has(it.rooms) && `<span><b>${it.rooms}</b> hab.</span>`,
    has(it.bathrooms) && `<span><b>${it.bathrooms}</b> baño${it.bathrooms > 1 ? "s" : ""}</span>`,
    has(it.price_per_m2) && `<span><b>${eur(it.price_per_m2)}</b>/m²</span>`,
    it.extra?.catastro?.anio_construccion && `<span>Año <b>${it.extra.catastro.anio_construccion}</b></span>`,
    it.cadastral_ref && it.kind !== "venta" && `<span class="ref">RC ${esc(it.cadastral_ref)}</span>`,
  ].filter(Boolean).join("");

  let block = "";
  if (it.kind === "subasta") {
    const x = it.extra || {};
    const rows = [
      ["Estado", it.status], ["Valor subasta", eur(it.auction_value)], ["Tasación", eur(it.appraisal)],
      ["Puja mínima", it.min_bid ? eur(it.min_bid) : ""], ["Depósito", eur(it.deposit)],
      ["Bajo tasación", has(it.discount_pct) ? `${num(it.discount_pct)} %` : ""],
      ["Cierre", fmtDate(it.end_date, true)], ["Reclamado", eur(it.claimed_debt)],
      ["Posesión", x.situacion_posesoria], ["Visitable", x.visitable], ["Puja actual", eur(x.puja_maxima_actual)],
    ].filter(([, v]) => has(v));
    block = `<dl class="auction">${rows.map(([k, v]) => `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>`;
  } else if (it.kind === "anuncio") {
    const x = it.extra || {};
    block = `<p class="muted small">${esc([it.seller, x.epigrafe, it.start_date && `publicado el ${fmtDate(it.start_date)}`].filter(Boolean).join(" · "))}</p>`;
  }

  const priceLabel = it.kind === "subasta" ? "valor de subasta" : it.kind === "anuncio" ? "" : "precio";
  const price = has(it.price)
    ? `<div class="price-wrap"><div class="price">${eur(it.price)}</div><div class="price-sub">${it.price_drop && it.previous_price ? `<span class="price-old">${eur(it.previous_price)}</span> · ` : ""}${priceLabel}</div></div>`
    : it.kind === "anuncio" ? "" : '<div class="price-wrap price-sub">Precio no publicado</div>';

  const links = [
    safeUrl(it.url) && `<a href="${esc(safeUrl(it.url))}" target="_blank" rel="noopener">${it.kind === "venta" ? "Ver anuncio" : it.kind === "subasta" ? "Ver ficha" : "Leer en el BOE"}</a>`,
    mapsUrl(it) && `<a href="${esc(mapsUrl(it))}" target="_blank" rel="noopener">Mapa</a>`,
    catastroUrl(it.cadastral_ref) && `<a href="${esc(catastroUrl(it.cadastral_ref))}" target="_blank" rel="noopener">Catastro</a>`,
  ].filter(Boolean).join("");

  const fav = it.marca === "favorito";
  const markControl = tracking
    ? `<select class="mark-select" data-action="mark" aria-label="Estado de seguimiento">${["", ...Object.keys(MARKS)].map((m) => `<option value="${m}" ${it.marca === m ? "selected" : ""}>${m ? MARKS[m] : "Quitar de seguimiento"}</option>`).join("")}</select>`
    : `<button type="button" class="icon-btn fav" data-action="fav" aria-pressed="${fav}" title="${fav ? "Quitar de favoritos" : "Guardar en favoritos"}" aria-label="Favorito">${ICON.star}</button>
       <button type="button" class="icon-btn discard" data-action="discard" aria-pressed="${it.marca === "descartado"}" title="Descartar" aria-label="Descartar">${ICON.x}</button>`;
  const noteOpen = state.openNotes.has(it.key);
  const note = noteOpen
    ? `<div class="note"><textarea id="note-${esc(it.key)}" aria-label="Nota">${esc(it.nota)}</textarea><div class="form-actions"><button type="button" class="btn btn-primary" data-action="save-note">Guardar nota</button><button type="button" class="btn btn-ghost" data-action="cancel-note">Cancelar</button></div></div>`
    : it.nota ? `<div class="note-saved">${esc(it.nota)}</div>` : "";

  return `<li class="ficha${it.vigente ? "" : " is-old"}${it.marca === "descartado" && !tracking ? " is-discarded" : ""}" data-key="${esc(it.key)}">
    <div class="ficha-tags">${tags.join("")}${ref ? `<span class="ref">${esc(ref)}</span>` : ""}</div>
    <div class="ficha-main">
      <h3 class="ficha-title">${safeUrl(it.url) ? `<a href="${esc(safeUrl(it.url))}" target="_blank" rel="noopener">${esc(titleOf(it))}</a>` : esc(titleOf(it))}</h3>
      ${place && it.kind !== "anuncio" ? `<div class="ficha-place">${esc(place)}</div>` : ""}
      ${facts ? `<div class="facts">${facts}</div>` : ""}
      ${block}
      ${it.description && it.kind !== "anuncio" ? `<p class="desc">${esc(it.description)}</p>` : ""}
    </div>
    <div class="ficha-side">
      ${price}
      <div class="actions">${markControl}<button type="button" class="icon-btn" data-action="note" title="Añadir nota" aria-label="Nota">${ICON.note}</button></div>
      <div class="links">${links}</div>
    </div>
    ${note}
  </li>`;
}

/* ───────── render ───────── */
function renderKpis() {
  const live = state.items.filter((i) => i.vigente);
  const today = new Date().toISOString().slice(0, 10);
  const k = [
    ["", live.length, "inmuebles encontrados"],
    ["is-new", live.filter((i) => i.is_new).length, "nuevos en la última búsqueda"],
    ["is-auction", live.filter((i) => i.kind === "subasta" && (!i.end_date || i.end_date.slice(0, 10) >= today)).length, "subastas abiertas o próximas"],
    ["is-drop", live.filter((i) => i.price_drop).length, "bajadas de precio"],
    ["", state.items.filter((i) => i.marca === "favorito").length, "favoritos"],
  ];
  $("#kpis").innerHTML = k.map(([cls, v, l]) => `<div class="kpi ${cls}"><div class="kpi-value">${num(v)}</div><div class="kpi-label">${l}</div></div>`).join("");
}
function renderResults() {
  const list = computeFiltered();
  const shown = list.slice(0, state.shown);
  const total = state.items.filter((i) => i.vigente).length;
  $("#results-count").textContent = state.items.length
    ? `${num(list.length)} de ${num(total)} inmuebles`
    : "";
  if (!state.items.length) {
    $("#list").innerHTML = `<li class="empty"><h3>Aún no hay resultados</h3><p>${isServer()
      ? "Revisa tus criterios y pulsa <b>Buscar ahora</b>. La primera búsqueda tarda unos minutos porque el bot abre cada subasta."
      : "Esta versión publicada todavía no tiene datos."}</p></li>`;
  } else if (!list.length) {
    $("#list").innerHTML = '<li class="empty"><h3>Nada con estos filtros</h3><p>Prueba a quitar alguno o pulsa <b>Limpiar</b>.</p></li>';
  } else {
    $("#list").innerHTML = shown.map((it) => ficha(it)).join("");
  }
  $("#more").hidden = list.length <= state.shown;
  $("#more").textContent = `Ver más (${num(list.length - state.shown)} restantes)`;
}
function renderTracking() {
  const tracked = state.items.filter((i) => i.marca);
  const counts = Object.fromEntries(Object.keys(MARKS).map((m) => [m, tracked.filter((i) => i.marca === m).length]));
  $("#count-seguimiento").textContent = tracked.filter((i) => i.marca !== "descartado").length || "";
  $("#track-filter").innerHTML = [["", "Todos"], ...Object.entries(MARKS)]
    .map(([v, l]) => `<button type="button" data-v="${v}" aria-pressed="${state.track === v}">${l}${v ? ` ${counts[v]}` : ""}</button>`).join("");
  const list = tracked.filter((i) => (state.track ? i.marca === state.track : i.marca !== "descartado"));
  $("#track-list").innerHTML = list.length
    ? sortItems(list, "recientes").map((it) => ficha(it, { tracking: true })).join("")
    : '<li class="empty"><h3>Nada en seguimiento</h3><p>Marca un inmueble con la estrella en <b>Resultados</b> para seguirlo aquí y añadirle notas.</p></li>';
}
function renderStatus() {
  const el = $("#status");
  if (!isServer()) {
    el.innerHTML = `Versión publicada · actualizada <b>${esc(fmtDate(state.generated, true))}</b>`;
    return;
  }
  if (jobRunning()) {
    const lines = state.job.log || [];
    const last = lines.length ? lines[lines.length - 1].texto.replace(/^\d\d:\d\d:\d\d /, "") : "";
    el.innerHTML = `<span class="pulse" aria-hidden="true"></span><b>${state.job.tipo === "diagnostico" ? "Diagnosticando" : "Buscando"}…</b> ${esc(last.slice(0, 110))}`;
  } else if (state.lastRun) {
    const r = state.lastRun;
    const errs = Object.keys(r.errors || {}).filter((k) => k !== "_").length;
    el.innerHTML = `Última búsqueda <b>${esc(ago(r.finished || r.started))}</b> · ${num(r.found)} resultados · ${num(r.new)} nuevos${errs ? ` · <span class="errs">${errs} web${errs > 1 ? "s" : ""} con problemas</span>` : ""}${state.nextRun ? ` · próxima ${esc(fmtDate(state.nextRun, true))}` : ""}`;
  } else {
    el.textContent = "Aún no has hecho ninguna búsqueda";
  }
  $("#btn-run").hidden = jobRunning();
  $("#btn-stop").hidden = !jobRunning();
  $("#btn-diag").disabled = jobRunning();
}
function renderJob() {
  if (!isServer()) return;
  const j = state.job;
  if (!j) { $("#job-state").textContent = "No hay ninguna búsqueda en marcha."; return; }
  const kind = j.tipo === "diagnostico" ? "Diagnóstico" : "Búsqueda";
  const st = { en_curso: "en marcha", terminado: "terminada", detenido: "detenida", error: "con error" }[j.estado] || j.estado;
  $("#job-state").textContent = `${kind} ${st} · empezó ${fmtDate(j.inicio, true)}${j.fin ? ` · acabó ${fmtDate(j.fin, true)}` : ""}${j.error ? ` · ${j.error}` : ""}`;
  if (j.tipo === "diagnostico" && j.resultado) {
    $("#diag-panel").hidden = false;
    $("#diag-intro").textContent = `Páginas guardadas en ${j.resultado.zip}. Si alguna web falla, comparte ese fichero o este texto para poder arreglarla.`;
    $("#diag-text").textContent = j.resultado.texto;
  }
}
function appendLog(lines) {
  const pre = $("#job-log");
  for (const l of lines) {
    const span = document.createElement("span");
    span.className = l.nivel;
    span.textContent = l.texto + "\n";
    pre.appendChild(span);
  }
  pre.scrollTop = pre.scrollHeight;
}
function renderHistory() {
  const rows = state.history || [];
  if (!rows.length) { $("#runs").innerHTML = '<tr><td class="muted">Todavía no hay búsquedas.</td></tr>'; return; }
  const dur = (r) => {
    if (!r.finished) return "—";
    const secs = Math.round((new Date(r.finished) - new Date(r.started)) / 1000);
    return secs < 60 ? `${secs} s` : `${Math.round(secs / 60)} min`;
  };
  const label = { ok: "Correcta", con_errores: "Con avisos", interrumpida: "Detenida", en_curso: "En marcha" };
  $("#runs").innerHTML = `<thead><tr><th>Fecha</th><th>Duración</th><th>Estado</th><th>Resultados</th><th>Nuevos</th><th>Webs con problemas</th></tr></thead><tbody>${rows.map((r) => {
    const errs = Object.entries(r.errors || {}).map(([k, v]) => `<div title="${esc(v)}">${esc(k === "_" ? "Error" : sourceName(k))}: ${esc(String(v).slice(0, 90))}</div>`).join("");
    return `<tr><td>${esc(fmtDate(r.started, true))}</td><td>${dur(r)}</td><td><span class="state state-${esc(r.status)}">${esc(label[r.status] || r.status)}</span></td><td>${num(r.found)}</td><td>${num(r.new)}</td><td class="errs">${errs || '<span class="muted">—</span>'}</td></tr>`;
  }).join("")}</tbody>`;
}
function renderAll() {
  renderKpis(); renderResults(); renderTracking(); renderStatus(); renderHistory(); renderJob();
}

/* ───────── vistas ───────── */
function selectView(view) {
  const ok = $$(".tab").some((t) => t.dataset.view === view && getComputedStyle(t).display !== "none");
  state.view = ok ? view : "resultados";
  for (const t of $$(".tab")) t.setAttribute("aria-selected", String(t.dataset.view === state.view));
  for (const v of $$(".view")) v.hidden = v.id !== `view-${state.view}`;
  store.set("vista", state.view);
  if (state.view === "criterios" && state.config) fillCriteriaForm();
  if (state.view === "ajustes" && state.config) fillSettingsForm();
}

/* ───────── marcas y notas ───────── */
async function setMark(key, patch) {
  const it = state.items.find((i) => i.key === key);
  if (!it) return;
  if (isServer()) {
    const r = await api(`api/inmuebles/${encodeURIComponent(key)}/marca`, { method: "POST", body: patch });
    it.marca = r.marca; it.nota = r.nota;
  } else {
    if ("marca" in patch) it.marca = patch.marca;
    if ("nota" in patch) it.nota = patch.nota;
    const marks = store.get("marcas", {});
    marks[key] = { marca: it.marca, nota: it.nota };
    store.set("marcas", marks);
  }
  renderKpis(); renderResults(); renderTracking();
}
async function onListClick(e) {
  const btn = e.target.closest("[data-action]");
  if (!btn || btn.tagName === "SELECT") return;
  const key = btn.closest("[data-key]").dataset.key;
  const it = state.items.find((i) => i.key === key);
  try {
    switch (btn.dataset.action) {
      case "fav": await setMark(key, { marca: it.marca === "favorito" ? "" : "favorito" }); toast(it.marca ? "Guardado en Seguimiento" : "Quitado de favoritos"); break;
      case "discard": await setMark(key, { marca: it.marca === "descartado" ? "" : "descartado" }); break;
      case "note": state.openNotes.add(key); renderResults(); renderTracking(); document.getElementById(`note-${key}`)?.focus(); break;
      case "cancel-note": state.openNotes.delete(key); renderResults(); renderTracking(); break;
      case "save-note": {
        const text = btn.closest(".note").querySelector("textarea").value.trim();
        state.openNotes.delete(key);
        await setMark(key, { nota: text });
        toast("Nota guardada");
        break;
      }
    }
  } catch (err) { toast(err.message); }
}
async function onListChange(e) {
  const sel = e.target.closest('select[data-action="mark"]');
  if (!sel) return;
  try { await setMark(sel.closest("[data-key]").dataset.key, { marca: sel.value }); toast("Seguimiento actualizado"); }
  catch (err) { toast(err.message); }
}

/* ───────── búsqueda y trabajos ───────── */
async function startSearch() {
  try {
    await api("api/busqueda", { method: "POST", body: {} });
    state.job = { tipo: "busqueda", estado: "en_curso", log: [], inicio: new Date().toISOString() };
    state.logSince = 0; $("#job-log").textContent = "";
    toast("Búsqueda iniciada. Puedes seguirla en Actividad.");
    renderStatus(); renderJob(); pollJob();
  } catch (err) { toast(err.message); }
}
async function startDiagnostic() {
  try {
    await api("api/diagnostico", { method: "POST", body: {} });
    state.job = { tipo: "diagnostico", estado: "en_curso", log: [], inicio: new Date().toISOString() };
    state.logSince = 0; $("#job-log").textContent = "";
    $("#diag-panel").hidden = true;
    toast("Diagnóstico iniciado (unos minutos)");
    renderStatus(); renderJob(); pollJob();
  } catch (err) { toast(err.message); }
}
async function pollJob() {
  clearTimeout(pollJob.timer);
  try {
    const j = await api(`api/trabajo?desde=${state.logSince}`);
    if (j) {
      if (j.log_total < state.logSince) { state.logSince = 0; $("#job-log").textContent = ""; }
      appendLog(j.log);
      state.logSince = j.log_total;
      const wasRunning = jobRunning();
      state.job = { ...j, log: [...(state.job?.log || []), ...j.log].slice(-50) };
      renderStatus(); renderJob();
      if (j.estado !== "en_curso") {
        if (wasRunning) await onJobFinished(j);
        return;
      }
    }
  } catch { /* se reintenta */ }
  pollJob.timer = setTimeout(pollJob, 1800);
}
async function onJobFinished(j) {
  if (j.tipo === "busqueda") {
    const r = j.resultado;
    toast(j.estado === "error" ? `La búsqueda falló: ${j.error}` : r ? `Búsqueda terminada: ${r.encontrados} resultados, ${r.nuevos} nuevos` : "Búsqueda terminada");
  } else {
    toast("Diagnóstico terminado: el resumen está en Actividad");
  }
  await Promise.all([loadItems(), loadHistory(), loadSummary()]).catch(() => {});
  buildFilterControls(); renderAll();
}
function startPolling() {
  setInterval(async () => {
    if (jobRunning()) return;
    try { await loadSummary(); renderStatus(); } catch { /* sin conexión */ }
  }, 30000);
}

/* ───────── criterios ───────── */
function selectedProvinceCodes(values) {
  const provs = state.meta.provincias;
  if (!values || !values.length || values.some((v) => ["todas", "all", "*"].includes(norm(v)))) return new Set(provs.map((p) => p.codigo));
  const out = new Set();
  for (const v of values) {
    const s = String(v).trim();
    if (/^\d{1,2}$/.test(s)) { out.add(s.padStart(2, "0")); continue; }
    const n = norm(s).replace(/ provincia$/, "");
    const p = provs.find((x) => x.nombre.split("/").some((part) => norm(part) === n));
    if (p) { out.add(p.codigo); continue; }
    for (const x of provs) if (norm(x.ccaa) === n) out.add(x.codigo);
  }
  return out;
}
function fillCriteriaForm() {
  const c = state.config.criterios;
  const chosen = selectedProvinceCodes(c.provincias);
  const groups = state.meta.ccaa.map((ccaa) => {
    const provs = state.meta.provincias.filter((p) => p.ccaa === ccaa);
    const all = provs.every((p) => chosen.has(p.codigo));
    return `<fieldset class="ccaa"><legend><label><input type="checkbox" data-ccaa="${esc(ccaa)}" ${all ? "checked" : ""}> ${esc(ccaa)}</label></legend>${provs.map((p) => `<label><input type="checkbox" name="prov" value="${p.codigo}" ${chosen.has(p.codigo) ? "checked" : ""}> ${esc(p.nombre)}</label>`).join("")}</fieldset>`;
  });
  $("#c-prov").innerHTML = groups.join("");
  $("#c-types").innerHTML = state.meta.tipos.map((t) => `<button type="button" class="chip" data-v="${t}" aria-pressed="${(c.tipos || []).includes(t)}">${esc(TYPE_LABEL[t] || t)}</button>`).join("");
  const val = (v) => (v == null ? "" : v);
  $("#c-loc").value = (c.localidades || []).join(", ");
  $("#c-cp").value = (c.codigos_postales || []).join(", ");
  $("#c-pmin").value = val(c.precio_min); $("#c-pmax").value = val(c.precio_max);
  $("#c-smin").value = val(c.superficie_min); $("#c-smax").value = val(c.superficie_max);
  $("#c-rooms").value = val(c.habitaciones_min); $("#c-disc").value = val(c.descuento_min);
  $("#c-kw").value = (c.palabras_clave || []).join(", ");
  $("#c-excl").value = (c.excluir_palabras || []).join(", ");
  $("#c-strict").checked = !!c.estricto;
  const f = state.config.fuentes;
  $("#c-sources").innerHTML = state.meta.fuentes.map((s) => {
    const o = f[s.id] || {};
    let opts = "";
    if (s.id === "boe") {
      opts = `<div class="inline"><span class="muted">Estados:</span>${Object.entries(BOE_STATES).map(([k, l]) => `<label class="check"><input type="checkbox" name="boe-estado" value="${k}" ${(o.estados || []).includes(k) ? "checked" : ""}> ${l}</label>`).join("")}</div>
        <div class="inline"><span class="muted">Solo de:</span>${Object.entries(ORIGINS).map(([k, l]) => `<label class="check"><input type="checkbox" name="boe-origen" value="${k}" ${(o.origenes || []).includes(k) ? "checked" : ""}> ${l}</label>`).join("")}<span class="muted small">(ninguno marcado = todos)</span></div>`;
    }
    if (s.id === "idealista") opts += `<label class="check"><input type="checkbox" id="src-idealista-bancos" ${o.solo_bancos ? "checked" : ""}> Solo pisos de bancos (necesita la clave de la API de Idealista)</label>`;
    if (s.id === "boe_anuncios") opts += `<label class="field"><span>Días hacia atrás</span><input type="number" id="src-dias" min="1" max="60" value="${esc(o.dias ?? 7)}"></label>`;
    if (URL_SOURCES.includes(s.id)) opts += `<label class="field"><span>Mis búsquedas en esta web (opcional, una URL por línea)</span><textarea id="src-urls-${s.id}" rows="2" placeholder="Pega aquí la URL de una búsqueda hecha en la web">${esc((o.urls || []).join("\n"))}</textarea></label>`;
    return `<div class="source"><div class="source-head"><label><input type="checkbox" name="src-on" value="${s.id}" ${o.activo !== false ? "checked" : ""}> ${esc(s.nombre)}</label><a class="small" href="${esc(safeUrl(s.web))}" target="_blank" rel="noopener">${esc(s.web.replace(/^https?:\/\/(www\.)?/, "").replace(/\/.*$/, ""))}</a></div>${opts ? `<div class="source-opts">${opts}</div>` : ""}</div>`;
  }).join("");
}
function readCriteriaForm() {
  const list = (s) => s.split(/[,\n]/).map((x) => x.trim()).filter(Boolean);
  const numOrNull = (s) => (s.trim() === "" ? null : Number(s));
  const provs = $$('input[name="prov"]:checked').map((i) => i.value);
  if (!provs.length) throw new Error("Elige al menos una provincia");
  const fuentes = {};
  for (const s of state.meta.fuentes) {
    const o = { activo: $(`input[name="src-on"][value="${s.id}"]`).checked };
    if (s.id === "boe") {
      o.estados = $$('input[name="boe-estado"]:checked').map((i) => i.value);
      o.origenes = $$('input[name="boe-origen"]:checked').map((i) => i.value);
      if (!o.estados.length) throw new Error("Marca al menos un estado de subasta del BOE");
    }
    if (s.id === "idealista") o.solo_bancos = $("#src-idealista-bancos").checked;
    if (s.id === "boe_anuncios") o.dias = Number($("#src-dias").value || 7);
    if (URL_SOURCES.includes(s.id)) o.urls = list($(`#src-urls-${s.id}`).value).filter((u) => /^https?:\/\//.test(u));
    fuentes[s.id] = o;
  }
  return {
    criterios: {
      provincias: provs.length === state.meta.provincias.length ? ["todas"] : provs,
      localidades: list($("#c-loc").value), codigos_postales: list($("#c-cp").value),
      tipos: $$("#c-types .chip[aria-pressed='true']").map((b) => b.dataset.v),
      precio_min: numOrNull($("#c-pmin").value), precio_max: numOrNull($("#c-pmax").value),
      superficie_min: numOrNull($("#c-smin").value), superficie_max: numOrNull($("#c-smax").value),
      habitaciones_min: numOrNull($("#c-rooms").value), descuento_min: numOrNull($("#c-disc").value),
      palabras_clave: list($("#c-kw").value), excluir_palabras: list($("#c-excl").value),
      estricto: $("#c-strict").checked,
    },
    fuentes,
  };
}
async function saveCriteria(thenRun) {
  try {
    state.config = await api("api/config", { method: "PUT", body: readCriteriaForm() });
    toast("Criterios guardados");
    if (thenRun) await startSearch();
  } catch (err) { toast(err.message); }
}

/* ───────── ajustes ───────── */
function fillSettingsForm() {
  const c = state.config;
  const auto = String(c.plataforma.auto_horas || 0);
  const sel = $("#s-auto");
  if (![...sel.options].some((o) => o.value === auto)) sel.insertAdjacentHTML("beforeend", `<option value="${esc(auto)}">${esc(auto)} horas</option>`);
  sel.value = auto;
  $("#s-tg-on").value = String(c.telegram.activo);
  $("#s-tg-token").value = "";
  $("#s-tg-token").placeholder = c.telegram.token.startsWith("${")
    ? "Se usa la variable de entorno TELEGRAM_TOKEN"
    : c.telegram.token || "123456:ABC…";
  $("#s-tg-chat").value = c.telegram.chat_id.startsWith("${") ? "" : c.telegram.chat_id;
  $("#s-browser").checked = !!c.red.navegador;
  $("#s-browser-visible").checked = !!c.red.navegador_visible;
  $("#s-catastro").checked = !!c.enriquecer_catastro;
  $("#s-pmin").value = c.red.pausa_min; $("#s-pmax").value = c.red.pausa_max;
}
async function saveSettings(e) {
  e.preventDefault();
  const on = $("#s-tg-on").value;
  const tg = { activo: on === "auto" ? "auto" : on === "true", chat_id: $("#s-tg-chat").value.trim() };
  if ($("#s-tg-token").value.trim()) tg.token = $("#s-tg-token").value.trim();
  try {
    state.config = await api("api/config", {
      method: "PUT",
      body: {
        plataforma: { auto_horas: Number($("#s-auto").value) },
        telegram: tg,
        red: {
          navegador: $("#s-browser").checked, navegador_visible: $("#s-browser-visible").checked,
          pausa_min: Number($("#s-pmin").value || 2), pausa_max: Number($("#s-pmax").value || 4),
        },
        enriquecer_catastro: $("#s-catastro").checked,
      },
    });
    fillSettingsForm();
    await loadSummary(); renderStatus();
    toast("Ajustes guardados");
  } catch (err) { toast(err.message); }
}

/* ───────── eventos ───────── */
function bindEvents() {
  for (const t of $$(".tab")) t.addEventListener("click", () => { location.hash = t.dataset.view; selectView(t.dataset.view); });
  window.addEventListener("hashchange", () => selectView(location.hash.slice(1)));

  const onFilter = () => { state.shown = PAGE; saveFilters(); renderResults(); };
  const bindInput = (id, key, prop = "value") => $(id).addEventListener(prop === "checked" ? "change" : "input", (e) => { state.filters[key] = e.target[prop]; onFilter(); });
  bindInput("#f-q", "q"); bindInput("#f-prov", "prov"); bindInput("#f-type", "type");
  bindInput("#f-pmin", "pmin"); bindInput("#f-pmax", "pmax"); bindInput("#f-m2", "m2"); bindInput("#f-rooms", "rooms");
  bindInput("#f-disc", "disc"); bindInput("#f-sort", "sort");
  bindInput("#f-new", "onlyNew", "checked"); bindInput("#f-drop", "onlyDrop", "checked");
  bindInput("#f-hide-discarded", "hideDiscarded", "checked"); bindInput("#f-old", "includeOld", "checked");
  $("#f-kind").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    state.filters.kind = b.dataset.v;
    for (const x of $$("#f-kind button")) x.setAttribute("aria-pressed", String(x === b));
    onFilter();
  });
  $("#f-source").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    const s = new Set(state.filters.sources);
    s.has(b.dataset.v) ? s.delete(b.dataset.v) : s.add(b.dataset.v);
    state.filters.sources = [...s];
    b.setAttribute("aria-pressed", String(s.has(b.dataset.v)));
    onFilter();
  });
  $("#f-reset").addEventListener("click", () => { state.filters = { ...DEFAULT_FILTERS }; buildFilterControls(); onFilter(); });
  $("#filters-toggle").addEventListener("click", (e) => {
    const open = $("#filters").classList.toggle("open");
    e.currentTarget.setAttribute("aria-expanded", String(open));
  });
  $("#more").addEventListener("click", () => { state.shown += PAGE; renderResults(); });

  for (const id of ["#list", "#track-list"]) {
    $(id).addEventListener("click", onListClick);
    $(id).addEventListener("change", onListChange);
  }
  $("#track-filter").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    state.track = b.dataset.v; renderTracking();
  });

  $("#btn-run").addEventListener("click", startSearch);
  $("#btn-stop").addEventListener("click", async () => {
    try { await api("api/busqueda/detener", { method: "POST", body: {} }); toast("Deteniendo… se guarda lo encontrado hasta ahora"); }
    catch (err) { toast(err.message); }
  });
  $("#btn-diag").addEventListener("click", startDiagnostic);

  $("#criteria-form").addEventListener("submit", (e) => { e.preventDefault(); saveCriteria(false); });
  $("#save-run").addEventListener("click", () => saveCriteria(true));
  $("#c-types").addEventListener("click", (e) => {
    const b = e.target.closest(".chip"); if (!b) return;
    b.setAttribute("aria-pressed", String(b.getAttribute("aria-pressed") !== "true"));
  });
  $("#c-prov").addEventListener("change", (e) => {
    const t = e.target;
    const fs = t.closest(".ccaa");
    if (t.dataset.ccaa) for (const i of $$('input[name="prov"]', fs)) i.checked = t.checked;
    else $("input[data-ccaa]", fs).checked = $$('input[name="prov"]', fs).every((i) => i.checked);
  });
  $("#settings-form").addEventListener("submit", saveSettings);
  $("#tg-test").addEventListener("click", async () => {
    try { await api("api/telegram/prueba", { method: "POST", body: {} }); toast("Mensaje enviado: revisa Telegram"); }
    catch (err) { toast(`No se pudo enviar: ${err.message}. Guarda primero el token y el chat id.`); }
  });
}

/* ───────── arranque ───────── */
async function init() {
  restoreFilters();
  try {
    state.meta = await api("api/meta");
    state.mode = "servidor";
  } catch {
    try {
      const res = await fetch("data.json", { cache: "no-store" });
      if (!res.ok) throw new Error();
      const data = await res.json();
      Object.assign(state, { mode: "estatico", meta: data.meta, items: data.inmuebles, history: data.historial, generated: data.generado });
      state.lastRun = data.resumen?.ultima_busqueda || null;
      indexItems(); applyLocalMarks();
    } catch {
      $("#status").textContent = "No se pudo cargar la plataforma.";
      $("#list").innerHTML = '<li class="empty"><h3>Sin conexión con CasaScan</h3><p>Arranca la plataforma con <code>python -m casascan web</code>.</p></li>';
      return;
    }
  }
  document.body.dataset.mode = state.mode;
  if (!isServer()) {
    for (const el of $$(".server-only, #btn-run, #btn-stop")) el.hidden = true;
    $("#static-banner").hidden = false;
    $("#static-banner").textContent = "Versión publicada de solo lectura. Tus favoritos y notas se guardan únicamente en este navegador.";
    $("#activity-intro").textContent = "Historial de las búsquedas del bot.";
  } else {
    await Promise.all([loadItems(), loadSummary(), loadConfig(), loadHistory()]).catch((err) => toast(err.message));
    startPolling();
  }
  buildFilterControls();
  bindEvents();
  renderAll();
  selectView(location.hash.slice(1) || store.get("vista", "resultados"));
}

init();
