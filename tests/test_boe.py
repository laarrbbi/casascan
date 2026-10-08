import pytest
from conftest import FakeHttp, load

from casascan.http import BlockedError
from casascan.sources.boe import BoeSource, lot_count, origin_of, parse_bien, parse_general, parse_search_results


def test_parse_search_results():
    items, next_href = parse_search_results(load("boe_resultados_p1.html"))
    assert [i["id"] for i in items] == ["SUB-JA-2026-265489", "SUB-AT-2026-26R2886001486"]
    first = items[0]
    assert first["status"] == "Celebrándose"
    assert first["end_date"] == "2026-10-19T18:00:00"
    assert first["expediente"] == "0000123/2024"
    assert "HUÉRCAL-OVERA" in first["authority"]
    assert next_href == "subastas_ava.php?accion=Mas&id_busqueda=_abc-50-50"


def test_parse_general_and_bien():
    g = parse_general(load("boe_general_265489.html"))
    assert g["valor_subasta"] == 99934.0
    assert g["tasacion"] == 142900.0
    assert g["puja_minima"] is None
    assert g["deposito"] == 4996.7
    assert g["cantidad_reclamada"] == 77816.01
    assert g["fecha_fin"] == "2026-10-19T18:00:00+02:00"
    assert lot_count(g["lotes"]) == 1
    b = parse_bien(load("boe_bien_265489.html"))
    assert b["localidad"] == "CUEVAS DE ALMANZORA"
    assert b["codigo_postal"] == "04610"
    assert b["referencia_catastral"] == "3045301WF3634N0157JY"
    assert "Vivienda" in b["tipo_bien"]


def test_origin_of():
    assert origin_of("SUB-JA-2026-1") == "judicial"
    assert origin_of("SUB-NE-2026-1") == "notarial"
    assert origin_of("SUB-AT-2026-1") == "agencia_tributaria"
    assert origin_of("SUB-RC-2026-1") == "administrativa"


def _route(method, url, data):
    if "subastas_ava.php" in url and method == "POST":
        return load("boe_resultados_p1.html"), 200
    if "id_busqueda=_abc-50-50" in url:
        return load("boe_resultados_p2.html"), 200
    if "SUB-JA-2026-265489" in url:
        return load("boe_bien_265489.html" if "ver=3" in url else "boe_general_265489.html"), 200
    if "SUB-NE-2026-470001" in url:
        if "ver=3" in url:
            return load(f"boe_bien_470001_L{url.split('idLote=')[1][0]}.html"), 200
        return load("boe_general_470001.html"), 200
    raise AssertionError(f"petición inesperada {method} {url}")


def test_boe_source_end_to_end():
    http = FakeHttp(_route)
    src = BoeSource(http, {"estados": ["EJ"]}, {"tipos": ["vivienda"], "excluir_palabras": ["aprovechamiento por turnos"]})
    results = list(src.search(["04"]))
    # La de multipropiedad (AT) se descarta por la descripción del listado sin abrir la ficha.
    assert not any("SUB-AT" in r.id for r in results)
    assert not any("SUB-AT" in url for _, url, _ in http.calls)
    ids = [r.id for r in results]
    assert ids == ["SUB-JA-2026-265489", "SUB-NE-2026-470001-L1", "SUB-NE-2026-470001-L2"]

    ja = results[0]
    assert ja.price == 99934.0 and ja.appraisal == 142900.0
    assert ja.discount_pct == pytest.approx(30.1, abs=0.1)
    assert ja.surface_m2 == 85.5 and ja.rooms == 3
    assert ja.city == "CUEVAS DE ALMANZORA" and ja.province_code == "04"
    assert ja.property_type == "vivienda"
    assert ja.extra["origen"] == "judicial"

    lot2 = results[2]
    assert lot2.price == 9000.0 and lot2.appraisal == 12000.0
    assert lot2.url.endswith("idLote=2")
    assert lot2.status == "Próxima apertura"
    # el formulario lleva la provincia y el subtipo de vivienda
    form = http.calls[0][2]
    assert form["dato[8]"] == "04" and form["dato[4]"] == "501" and form["dato[2]"] == "EJ"


def test_boe_origin_filter_skips_details():
    http = FakeHttp(_route)
    src = BoeSource(http, {"estados": ["EJ"], "origenes": ["notarial"]}, {"tipos": ["vivienda"]})
    results = list(src.search(["04"]))
    assert {r.extra["origen"] for r in results} == {"notarial"}
    assert not any("SUB-JA" in url for _, url, _ in http.calls)


def test_boe_captcha_raises():
    http = FakeHttp(lambda m, u, d: (load("boe_captcha.html"), 200))
    with pytest.raises(BlockedError):
        list(BoeSource(http, {}, {"tipos": ["vivienda"]}).search(["28"]))


def test_boe_detail_cache_avoids_refetching(tmp_path):
    from casascan.storage import Storage

    storage = Storage(str(tmp_path / "c.db"))
    criteria = {"tipos": ["vivienda"], "excluir_palabras": ["aprovechamiento por turnos"]}
    first = FakeHttp(_route)
    r1 = list(BoeSource(first, {"estados": ["EJ"]}, criteria, cache=storage).search(["04"]))
    assert any("detalleSubasta" in url for _, url, _ in first.calls)

    second = FakeHttp(_route)
    r2 = list(BoeSource(second, {"estados": ["EJ"]}, criteria, cache=storage).search(["04"]))
    assert not any("detalleSubasta" in url for _, url, _ in second.calls)
    assert [(r.id, r.price, r.status) for r in r2] == [(r.id, r.price, r.status) for r in r1]
