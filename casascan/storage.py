"""Memoria del bot (SQLite): qué se ha visto ya, cuándo, y a qué precio.

Permite marcar los resultados NUEVOS y las BAJADAS de precio entre ejecuciones.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

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
"""


class Storage:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    def record(self, item: Listing, now: str | None = None) -> Listing:
        """Guarda el resultado y rellena is_new / previous_price / first_seen."""
        now = now or datetime.now().isoformat(timespec="seconds")
        row = self.conn.execute(
            "SELECT first_seen, price FROM listings WHERE key = ?", (item.key,)
        ).fetchone()
        if row is None:
            item.is_new = True
            item.first_seen = now
            self.conn.execute(
                "INSERT INTO listings (key, source, first_seen, last_seen, price, data) VALUES (?,?,?,?,?,?)",
                (item.key, item.source, now, now, item.price, json.dumps(item.to_dict(), ensure_ascii=False)),
            )
            self.conn.execute("INSERT INTO price_history VALUES (?,?,?)", (item.key, now, item.price))
        else:
            first_seen, old_price = row
            item.is_new = False
            item.first_seen = first_seen
            if old_price is not None and item.price is not None and item.price != old_price:
                item.previous_price = old_price
                self.conn.execute("INSERT INTO price_history VALUES (?,?,?)", (item.key, now, item.price))
            self.conn.execute(
                "UPDATE listings SET last_seen = ?, price = ?, data = ? WHERE key = ?",
                (now, item.price, json.dumps(item.to_dict(), ensure_ascii=False), item.key),
            )
        return item

    # Caché de fichas de detalle (evita reabrir cada subasta en cada ejecución)
    def cache_get(self, key: str, max_age_hours: float) -> list[dict] | None:
        row = self.conn.execute("SELECT fetched_at, data FROM detail_cache WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        if datetime.fromisoformat(row[0]) < datetime.now() - timedelta(hours=max_age_hours):
            return None
        return json.loads(row[1])

    def cache_put(self, key: str, listings: list[Listing]) -> None:
        data = json.dumps([x.to_dict() for x in listings], ensure_ascii=False)
        self.conn.execute(
            "INSERT OR REPLACE INTO detail_cache (key, fetched_at, data) VALUES (?,?,?)",
            (key, datetime.now().isoformat(timespec="seconds"), data),
        )
        self.conn.commit()

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()
