import json
from datetime import date, timedelta

from conftest import FakeHttp, load

from casascan.catastro import parse_dnprc
from casascan.sources.aliseda import AlisedaSource
from casascan.sources.boe_anuncios import BoeAnunciosSource, iter_items
from casascan.sources.fotocasa import FotocasaSource, build_web_url, listing_from_ad, pick_location
from casascan.sources.generic import extract_listings
from casascan.sources.idealista import IdealistaSource, page_url, parse_search_page
from casascan.sources.idealista import build_web_url as idealista_url
from casascan.sources.seguridad_social import SeguridadSocialSource, parse_detail, parse_listing_page
from casascan.sources.servicer import with_page


# ------------------------------------------------------------ Seguridad Social
def test_ss_listing_maps_columns_by_header():
    lots = parse_listing_page(load("ss_listado.html"))
    assert [lot["emb_id"] for lot in lots] == ["123456", "123457"]
    first = lots[0]
    assert first["tasacion"] == 150000.0
    assert first["cargas"] == 10000.0
    assert first["valor"] == 140000.0
    assert first["fecha"] == "15/11/2026 10:00"
    assert first["tipo_bien"] == "Finca Urbana" and first["provincia"] == "MADRID"


def test_ss_source_end_to_end():
    def route(method, url, data):
        if "opcion=6" in url:
            return "<html>busqueda</html>", 200
        if method == "POST":
            assert ("provincia", "28") in data and ("EMB_TIPOBIEN", "0102") in data
            return load("ss_listado.html"), 200
        if "pagina=" in url:
            return "<html>sin resultados</html>", 200
        if "opcion=13" in url:
            return load("ss_detalle.html"), 200
        raise AssertionError(url)

    src = SeguridadSocialSource(FakeHttp(route), {}, {"tipos": ["vivienda"]})
    res = list(src.search(["28"]))
    assert len(res) == 2
    viv = res[0]
    assert viv.price == 140000.0 and viv.appraisal == 150000.0
    assert viv.postal_code == "28009" and viv.city == "MADRID"
    assert viv.surface_m2 == 75.0 and viv.rooms == 2
    assert viv.cadastral_ref == "1234567VK4713S0001AB"
    assert viv.end_date == "2026-11-15T10:00:00"
    assert viv.property_type == "vivienda"
    assert parse_detail(load("ss_detalle.html"))["expediente"] == ["28 07 12 00123456"]


# ------------------------------------------------------------------ Idealista
def test_idealista_parse_search_page():
    items, has_next = parse_search_page(load("idealista_listado.html"))
    assert has_next
    assert [i["id"] for i in items] == ["104567890", "104567891"]
    first = items[0]
    assert first["price"] == 145000.0 and first["rooms"] == 3 and first["surface_m2"] == 85.0
    assert first["url"] == "https://www.idealista.com/inmueble/104567890/"
    assert first["seller"] == "Aliseda Inmobiliaria"


def test_idealista_urls():
    assert idealista_url("29", "vivienda", {"precio_max": 120000}) == (
        "https://www.idealista.com/venta-viviendas/malaga-provincia/con-precio-hasta_120000/"
        "?ordenado-por=fecha-publicacion-desc"
    )
    assert "/balears-illes/" in idealista_url("07", "vivienda", {})
    assert page_url("https://www.idealista.com/venta-viviendas/madrid-provincia/?a=1", 3) == (
        "https://www.idealista.com/venta-viviendas/madrid-provincia/pagina-3.htm?a=1"
    )


def test_idealista_html_source_uses_city_and_province():
    http = FakeHttp(lambda m, u, d: (load("idealista_listado.html") if "pagina" not in u else "<html></html>", 200))
    res = list(IdealistaSource(http, {"max_paginas": 2}, {"tipos": ["vivienda"]}).search(["28"]))
    assert len(res) == 2
    assert res[0].city == "Madrid" and res[0].province_code == "28" and res[0].property_type == "vivienda"


def test_idealista_api(monkeypatch):
    monkeypatch.setenv("IDEALISTA_API_KEY", "k")
    monkeypatch.setenv("IDEALISTA_API_SECRET", "s")
    api_page = {
        "totalPages": 1,
        "elementList": [{
            "propertyCode": "999", "price": 99000.0, "size": 70.0, "rooms": 2, "bathrooms": 1,
            "address": "Calle Sol", "municipality": "Getafe", "province": "Madrid", "propertyType": "flat",
            "url": "https://www.idealista.com/inmueble/999/", "latitude": 40.3, "longitude": -3.7,
        }],
    }

    def route(method, url, data):
        if "oauth/token" in url:
            return json.dumps({"access_token": "T"}), 200
        assert data["locationId"] == "0-EU-ES-28" and data["bankOffer"] == "true" and data["maxPrice"] == 100000
        return json.dumps(api_page), 200

    src = IdealistaSource(FakeHttp(route), {"solo_bancos": True}, {"precio_max": 100000, "tipos": ["vivienda"]})
    res = list(src.search(["28"]))
    assert len(res) == 1 and res[0].city == "Getafe" and res[0].property_type == "vivienda"


# ------------------------------------------------------------------- Fotocasa
def test_fotocasa_listing_from_ad():
    ad = {
        "propertyId": 185000111,
        "price": 120000,
        "rooms": 3,
        "bathrooms": 1,
        "surface": 90,
        "description": "Piso luminoso",
        "location": {"level2Name": "Madrid", "level5Name": "Getafe"},
        "detail": {"es-ES": "/es/comprar/vivienda/getafe/ascensor/185000111/d"},
        "agency": {"id": 5, "name": "Agencia"},
    }
    d = listing_from_ad(ad)
    assert d["id"] == "185000111"
    assert d["price"] == 120000 and d["rooms"] == 3 and d["surface_m2"] == 90
    assert d["url"] == "https://www.fotocasa.es/es/comprar/vivienda/getafe/ascensor/185000111/d"
    assert d["city"] == "Getafe" and d["province"] == "Madrid"


def test_fotocasa_pick_location_and_url():
    sugg = [
        {"text": "Madrid Capital", "type": "CITY", "combinedLocationIds": "a", "adsCount": 900},
        {"text": "Madrid provincia", "type": "PROVINCE", "combinedLocationIds": "b", "adsCount": 500},
    ]
    assert pick_location(sugg, "28")["combinedLocationIds"] == "b"
    assert build_web_url("29", "vivienda", {"precio_max": 1e5, "habitaciones_min": 2}) == (
        "https://www.fotocasa.es/es/comprar/viviendas/malaga-provincia/todas-las-zonas/l?maxPrice=100000&minRooms=2"
    )


def test_fotocasa_falls_back_to_web_when_api_blocked():
    def route(method, url, data):
        if "gw.fotocasa.es" in url:
            return "<html>blocked</html>", 200  # no es JSON -> ValueError -> web
        return load("generic_nextdata.html"), 200

    src = FotocasaSource(FakeHttp(route), {"max_paginas": 1}, {"tipos": ["vivienda"]})
    res = list(src.search(["29"]))
    assert {r.id for r in res} >= {"ALS-0002", "SH-778899"}


# ----------------------------------------------------------- genérico / Sareb
def test_generic_extract_all_strategies():
    items = {i["id"] or i["url"]: i for i in extract_listings(load("generic_nextdata.html"), "https://example.com/x")}
    ld = next(i for i in items.values() if i["url"].endswith("ALS-0001"))
    assert ld["price"] == 189000 and ld["city"] == "Málaga" and ld["postal_code"] == "29005"
    assert ld["rooms"] == 3 and ld["surface_m2"] == 95
    nxt = items["ALS-0002"]
    assert nxt["price"] == 210000 and nxt["surface_m2"] == 72 and nxt["lat"] == 36.62
    js = items["SH-778899"]
    assert js["price"] == 99500 and js["surface_m2"] == 64 and js["city"] == "Vélez-Málaga"
    card = next(i for i in items.values() if "12345" in i["url"])
    assert card["price"] == 130000 and card["rooms"] == 4
    # el objeto de filtros {"min":0,"max":500000} no es un anuncio
    assert all(i["price"] != 500000 for i in items.values())


def test_with_page():
    assert with_page("https://x.es/a?page=3&b=1", 2) == "https://x.es/a?b=1&page=2"
    assert with_page("https://x.es/a?page=3", 1) == "https://x.es/a"


def test_aliseda_discovers_province_link():
    home = '<a href="/comprar-viviendas/andalucia/malaga">Málaga</a><a href="/comprar-viviendas/andalucia/cadiz">Cádiz</a>'

    def route(method, url, data):
        if url.rstrip("/") in ("https://www.alisedainmobiliaria.com", "https://www.alisedainmobiliaria.com/comprar-viviendas"):
            return home, 200
        if url == "https://www.alisedainmobiliaria.com/comprar-viviendas/andalucia/malaga":
            return load("generic_nextdata.html"), 200
        return "<html></html>", 200

    src = AlisedaSource(FakeHttp(route), {"max_paginas": 2}, {})
    res = list(src.search(["29"]))
    assert len(res) >= 4
    assert all(r.seller == "Aliseda / Sareb" for r in res)
    assert {r.province_code for r in res} == {"29"}


# ------------------------------------------------------- BOE pre-subasta
def test_boe_sumario_walk_and_filter():
    data = json.loads(load("boe_sumario.json"))
    items = list(iter_items(data["data"]))
    assert len(items) == 4
    item, ctx = items[0]
    assert ctx["seccion_codigo"] == "4" and ctx["epigrafe"] == "MÁLAGA"

    sumario = load("boe_sumario.json")
    today = date.today()
    last_weekday = today if today.weekday() != 6 else today - timedelta(days=1)

    def route(method, url, data):
        return (sumario, 200) if last_weekday.strftime("%Y%m%d") in url else ("", 404)

    src = BoeAnunciosSource(FakeHttp(route), {"dias": 2}, {})
    res = list(src.search(["29"]))
    ids = {r.id for r in res}
    assert ids == {"BOE-B-2026-40001", "BOE-B-2026-40004"}  # Málaga: edicto + notaría de Marbella (Málaga)
    notaria = next(r for r in res if r.id == "BOE-B-2026-40004")
    assert notaria.url == "https://www.boe.es/diario_boe/txt.php?id=BOE-B-2026-40004"
    assert notaria.province_code == "29" and notaria.seller == "NOTARÍAS"


# ------------------------------------------------------------------- Catastro
def test_parse_dnprc():
    d = parse_dnprc(load("catastro_dnprc.xml"))
    assert d["uso"] == "Residencial" and d["superficie_m2"] == 85.0 and d["anio_construccion"] == 1985
    assert parse_dnprc("no xml") == {}
