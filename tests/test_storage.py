import pytest

from casascan.models import Listing
from casascan.storage import Storage


def item(id_, price, source="boe"):
    return Listing(source=source, id=id_, url=f"https://x/{id_}", price=price, province_code="28")


def test_runs_vigente_new_and_price_drop(tmp_path):
    s = Storage(str(tmp_path / "s.db"))
    r1 = s.start_run(["boe", "idealista"])
    s.record(item("a", 100), run_id=r1)
    s.record(item("b", 200), run_id=r1)
    s.record(item("z", 50, "idealista"), run_id=r1)
    s.finish_run(r1, {"boe": [2, 2], "idealista": [1, 1]}, {}, False, 3, 3)

    r2 = s.start_run(["boe", "idealista"])
    s.record(item("a", 90), run_id=r2)       # baja de precio, sigue
    s.record(item("c", 300), run_id=r2)      # nuevo
    # "b" ya no aparece; idealista falla en esta búsqueda
    s.finish_run(r2, {"boe": [2, 2], "idealista": [0, 0]}, {"idealista": "bloqueado"}, False, 2, 1)

    rows = {r["key"]: r for r in s.listings()}
    assert rows["boe:a"]["vigente"] and rows["boe:a"]["price_drop"] and rows["boe:a"]["previous_price"] == 100
    assert rows["boe:c"]["is_new"] and rows["boe:c"]["vigente"]
    assert not rows["boe:b"]["vigente"]
    # idealista falló en la última: lo de su última búsqueda correcta sigue vigente
    assert rows["idealista:z"]["vigente"]
    runs = s.runs()
    assert [r["status"] for r in runs] == ["con_errores", "ok"]
    assert runs[0]["sources_ok"] == ["boe"]
    assert [p["price"] for p in s.price_history("boe:a")] == [100, 90]


def test_marks(tmp_path):
    s = Storage(str(tmp_path / "m.db"))
    s.record(item("a", 100))
    assert s.set_mark("boe:a", estado="favorito") == {"key": "boe:a", "marca": "favorito", "nota": ""}
    s.set_mark("boe:a", nota="Llamar al juzgado")
    row = s.listings()[0]
    assert row["marca"] == "favorito" and row["nota"] == "Llamar al juzgado"
    with pytest.raises(ValueError):
        s.set_mark("boe:a", estado="raro")


def test_migrates_old_database(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE listings (key TEXT PRIMARY KEY, source TEXT NOT NULL, first_seen TEXT NOT NULL, "
        "last_seen TEXT NOT NULL, price REAL, data TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO listings VALUES ('boe:x','boe','2026-01-01','2026-01-01',1,'{\"id\":\"x\"}')")
    conn.commit()
    conn.close()
    rows = Storage(str(path)).listings()
    assert rows[0]["key"] == "boe:x" and rows[0]["vigente"]
