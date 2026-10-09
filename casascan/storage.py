"""Memoria del bot (SQLite).

Guarda todo lo encontrado, cuándo se vio por primera y última vez, los cambios
de precio, el historial de búsquedas y las marcas del usuario (favorito,
descartado, notas). Permite marcar lo NUEVO, las BAJADAS de precio y lo que
ya no aparece en las webs.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from .models import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    key         TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    price       REAL,
    data        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS price_history (
    key   TEXT NOT NULL,
    seen  TEXT NOT NULL,
    price REAL
);
CREATE TABLE IF NOT EXISTS detail_cache (
    key        TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    data       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started     TEXT NOT NULL,
    finished    TEXT,
    status      TEXT NOT NULL DEFAULT 'en_curso',
    sources     TEXT NOT NULL DEFAULT '[]',
    sources_ok  TEXT NOT NULL DEFAULT '[]',
    stats       TEXT NOT NULL DEFAULT '{}',
    errors      TEXT NOT NULL DEFAULT '{}',
    found       INTEGER NOT NULL DEFAULT 0,
    new         INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS marks (
    key      TEXT PRIMARY KEY,
    estado   TEXT NOT NULL DEFAULT '',
    nota     TEXT NOT NULL DEFAULT '',
    updated  TEXT NOT NULL
);
"""

# Columnas añadidas después de la primera versión (se crean si faltan)
_MIGRATIONS = {
    "first_run": "INTEGER",
    "last_run": "INTEGER",
    "prev_price": "REAL",
    "price_changed": "TEXT",
}

MARK_STATES = ("", "favorito", "descartado", "contactado", "visitado")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Storage:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(listings)")}
        for col, typ in _MIGRATIONS.items():
            if col not in cols:
                self.conn.execute(f"ALTER TABLE listings ADD COLUMN {col} {typ}")
        self.conn.commit()

    # ------------------------------------------------------------- resultados
    def record(self, item: Listing, now: str | None = None, run_id: int | None = None) -> Listing:
        """Guarda el resultado y rellena is_new / previous_price / first_seen."""
        now = now or _now()
        row = self.conn.execute(
            "SELECT first_seen, price, prev_price, price_changed FROM listings WHERE key = ?", (item.key,)
        ).fetchone()
        if row is None:
            item.is_new = True
            item.first_seen = now
            self.conn.execute(
                "INSERT INTO listings (key, source, first_seen, last_seen, price, data, first_run, last_run) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (item.key, item.source, now, now, item.price, self._dump(item), run_id, run_id),
            )
            self.conn.execute("INSERT INTO price_history VALUES (?,?,?)", (item.key, now, item.price))
        else:
            item.is_new = False
            item.first_seen = row["first_seen"]
            old_price, prev_price, changed = row["price"], row["prev_price"], row["price_changed"]
            if old_price is not None and item.price is not None and item.price != old_price:
                item.previous_price = old_price
                prev_price, changed = old_price, now
                self.conn.execute("INSERT INTO price_history VALUES (?,?,?)", (item.key, now, item.price))
            self.conn.execute(
                "UPDATE listings SET last_seen = ?, price = ?, data = ?, last_run = COALESCE(?, last_run), "
                "prev_price = ?, price_changed = ? WHERE key = ?",
                (now, item.price, self._dump(item), run_id, prev_price, changed, item.key),
            )
        return item

    @staticmethod
    def _dump(item: Listing) -> str:
        return json.dumps(item.to_dict(), ensure_ascii=False)

    def listings(self) -> list[dict[str, Any]]:
        """Todos los resultados guardados con su estado (vigente, nuevo, bajada, marca)."""
        latest_ok = self.latest_ok_runs()
        last_run = self.conn.execute("SELECT MAX(id) FROM runs WHERE status != 'en_curso'").fetchone()[0]
        out = []
        rows = self.conn.execute(
            "SELECT l.*, m.estado, m.nota FROM listings l LEFT JOIN marks m ON m.key = l.key"
        ).fetchall()
        for r in rows:
            d = json.loads(r["data"])
            ok_run = latest_ok.get(r["source"])
            d.update(
                key=r["key"],
                first_seen=r["first_seen"],
                last_seen=r["last_seen"],
                price=r["price"],
                previous_price=r["prev_price"],
                price_changed=r["price_changed"] or "",
                price_drop=bool(r["prev_price"] and r["price"] is not None and r["price"] < r["prev_price"]),
                # vigente: apareció en la última búsqueda correcta de su fuente
                vigente=ok_run is None or r["last_run"] is None or r["last_run"] >= ok_run,
                is_new=bool(r["first_run"] and last_run and r["first_run"] == last_run),
                marca=r["estado"] or "",
                nota=r["nota"] or "",
            )
            out.append(d)
        return out

    def price_history(self, key: str) -> list[dict]:
        rows = self.conn.execute("SELECT seen, price FROM price_history WHERE key = ? ORDER BY seen", (key,))
        return [dict(r) for r in rows]

    # ----------------------------------------------------------------- marcas
    def set_mark(self, key: str, estado: str | None = None, nota: str | None = None) -> dict:
        if estado is not None and estado not in MARK_STATES:
            raise ValueError(f"Estado no válido: {estado}")
        cur = self.conn.execute("SELECT estado, nota FROM marks WHERE key = ?", (key,)).fetchone()
        estado = estado if estado is not None else (cur["estado"] if cur else "")
        nota = nota if nota is not None else (cur["nota"] if cur else "")
        self.conn.execute(
            "INSERT OR REPLACE INTO marks (key, estado, nota, updated) VALUES (?,?,?,?)", (key, estado, nota, _now())
        )
        self.conn.commit()
        return {"key": key, "marca": estado, "nota": nota}

    # --------------------------------------------------------------- búsquedas
    def start_run(self, sources: list[str]) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (started, sources) VALUES (?, ?)", (_now(), json.dumps(sources))
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, stats: dict, errors: dict, interrupted: bool, found: int, new: int) -> None:
        ok = [s for s in stats if s not in errors] if not interrupted else []
        status = "interrumpida" if interrupted else ("con_errores" if errors else "ok")
        self.conn.execute(
            "UPDATE runs SET finished = ?, status = ?, sources_ok = ?, stats = ?, errors = ?, found = ?, new = ? "
            "WHERE id = ?",
            (_now(), status, json.dumps(ok), json.dumps(stats), json.dumps(errors, ensure_ascii=False),
             found, new, run_id),
        )
        self.conn.commit()

    def runs(self, limit: int = 30) -> list[dict]:
        out = []
        for r in self.conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)):
            d = dict(r)
            for k in ("sources", "sources_ok", "stats", "errors"):
                d[k] = json.loads(d[k])
            out.append(d)
        return out

    def latest_ok_runs(self) -> dict[str, int]:
        """Última búsqueda correcta de cada fuente: {fuente: id de búsqueda}."""
        latest: dict[str, int] = {}
        for r in self.conn.execute("SELECT id, sources_ok FROM runs WHERE finished IS NOT NULL ORDER BY id"):
            for s in json.loads(r["sources_ok"]):
                latest[s] = r["id"]
        return latest

    # Caché de fichas de detalle (evita reabrir cada subasta en cada ejecución)
    def cache_get(self, key: str, max_age_hours: float) -> list[dict] | None:
        row = self.conn.execute("SELECT fetched_at, data FROM detail_cache WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        if datetime.fromisoformat(row["fetched_at"]) < datetime.now() - timedelta(hours=max_age_hours):
            return None
        return json.loads(row["data"])

    def cache_put(self, key: str, listings: list[Listing]) -> None:
        data = json.dumps([x.to_dict() for x in listings], ensure_ascii=False)
        self.conn.execute(
            "INSERT OR REPLACE INTO detail_cache (key, fetched_at, data) VALUES (?,?,?)", (key, _now(), data)
        )
        self.conn.commit()

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()
