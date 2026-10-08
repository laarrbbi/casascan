import csv

from casascan import runner
from casascan.config import Config
from casascan.criteria import Criteria
from casascan.models import ANUNCIO, SUBASTA, Listing
from casascan.report import write_reports
from casascan.sources.base import Source
from casascan.storage import Storage


def make(**kw) -> Listing:
    base = dict(source="test", id="1", url="https://x/1", province_code="28", property_type="vivienda")
    base.update(kw)
    return Listing(**base)


def test_criteria_basic_and_missing_data():
    c = Criteria({"provincias": ["Madrid"], "tipos": ["vivienda"], "precio_max": 150000,
                  "superficie_min": 50, "habitaciones_min": 2, "excluir_palabras": ["nuda propiedad"]})
    assert c.matches(make(price=100000, surface_m2=60, rooms=2))
    assert c.reasons_to_reject(make(price=200000)) == ["precio máximo"]
    assert c.reasons_to_reject(make(price=100000, province_code="29")) == ["provincia"]
    assert "tipo" in c.reasons_to_reject(make(property_type="garaje"))
    assert "palabra excluida" in c.reasons_to_reject(make(description="Subasta de la NUDA PROPIEDAD"))
    # dato que falta: pasa en modo normal, se descarta en modo estricto
    assert c.matches(make(price=None, surface_m2=None))
    strict = Criteria({"provincias": ["28"], "precio_max": 150000, "estricto": True})
    assert strict.reasons_to_reject(make(price=None)) == ["sin dato: precio máximo"]


def test_criteria_discount_and_cities_and_notices():
    c = Criteria({"provincias": ["28"], "descuento_min": 30, "localidades": ["Getafe"]})
    assert c.matches(make(kind=SUBASTA, price=60000, appraisal=100000, city="GETAFE"))
    assert "descuento sobre tasación" in c.reasons_to_reject(make(kind=SUBASTA, price=90000, appraisal=100000, city="Getafe"))
    assert "localidad" in c.reasons_to_reject(make(city="Leganés"))
    assert c.matches(make(city=""))  # sin localidad conocida: no se descarta
    notice = make(kind=ANUNCIO, title="Subasta notarial de finca en Getafe", property_type="", price=None)
    assert c.matches(notice)


def test_storage_new_and_price_drop(tmp_path):
    db = str(tmp_path / "t.db")
    s = Storage(db)
    a = s.record(make(price=100000), now="2026-10-01T10:00:00")
    assert a.is_new
    s.close()
    s = Storage(db)
    b = s.record(make(price=100000))
    assert not b.is_new and not b.price_drop and b.first_seen == "2026-10-01T10:00:00"
    c = s.record(make(price=90000))
    assert c.price_drop and c.previous_price == 100000
    s.close()


def test_reports(tmp_path):
    items = [make(price=95000, surface_m2=70, title="Piso <script>", cadastral_ref="3045301WF3634N0157JY", is_new=True)]
    files = write_reports(items, str(tmp_path), ["csv", "html", "json"], {"idealista": "bloqueado"})
    names = {f.name for f in files}
    assert {"ultimo.csv", "ultimo.html", "ultimo.json"} <= names
    rows = list(csv.reader(open(tmp_path / "ultimo.csv", encoding="utf-8-sig"), delimiter=";"))
    header = rows[0]
    assert rows[1][header.index("eur_m2")] == "1357.14"
    assert rows[1][header.index("catastro")].endswith("rc1=3045301&rc2=WF3634N")
    html = (tmp_path / "ultimo.html").read_text(encoding="utf-8")
    assert "Piso &lt;script&gt;" in html and "bloqueado" in html and "NUEVO" in html


class DummySource(Source):
    name = "dummy"
    label = "Dummy"

    def search(self, provinces):
        yield make(source="dummy", id="a", price=100000, surface_m2=80, rooms=3)
        yield make(source="dummy", id="b", price=500000, surface_m2=80, rooms=3)  # demasiado caro
        yield make(source="dummy", id="a", price=100000, surface_m2=80, rooms=3)  # duplicado


class BrokenSource(Source):
    name = "broken"
    label = "Broken"

    def search(self, provinces):
        raise RuntimeError("web caída")
        yield  # pragma: no cover


def test_runner(tmp_path, monkeypatch):
    monkeypatch.setitem(runner.SOURCES, "dummy", DummySource)
    monkeypatch.setitem(runner.SOURCES, "broken", BrokenSource)
    cfg = Config({
        "criterios": {"provincias": ["Madrid"], "precio_max": 200000},
        "red": {"pausa_min": 0, "pausa_max": 0},
        "salida": {"carpeta": str(tmp_path / "out"), "base_datos": str(tmp_path / "db.sqlite"), "formatos": ["csv"]},
    })
    res = runner.run(cfg, ["dummy", "broken"])
    assert [i.id for i in res.items] == ["a"]
    assert res.items[0].is_new
    assert res.stats["dummy"] == (3, 2) and "broken" in res.errors
    assert (tmp_path / "out" / "ultimo.csv").exists()
    # segunda ejecución: ya no es nuevo
    res2 = runner.run(cfg, ["dummy"])
    assert not res2.items[0].is_new and res2.new_items == []
