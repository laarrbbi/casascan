import pytest

from casascan.provinces import province_code, province_slugs, resolve_provinces
from casascan.textutil import find_cadastral_ref, parse_date, parse_euros, parse_m2, parse_rooms


@pytest.mark.parametrize(
    "text,expected",
    [
        ("36.060,73 €", 36060.73),
        ("150.000€", 150000.0),
        ("99.934,00 EUR", 99934.0),
        ("1.250", 1250.0),
        ("Sin puja mínima", None),
        ("Ver valor de subasta en cada lote", None),
        (189000, 189000.0),
        ("", None),
        (None, None),
    ],
)
def test_parse_euros(text, expected):
    assert parse_euros(text) == expected


def test_parse_m2_takes_largest_and_hectares():
    assert parse_m2("útil 70 m2, construida 85,50 m²") == 85.5
    assert parse_m2("finca de 2,5 hectáreas") == 25000.0
    assert parse_m2("sin superficie") is None


def test_parse_rooms():
    assert parse_rooms("3 hab. 85 m²") == 3
    assert parse_rooms("distribuida en 2 dormitorios") == 2


def test_parse_date_formats():
    assert parse_date("19-10-2026 18:00:00 CET (ISO: 2026-10-19T18:00:00+02:00)") == "2026-10-19T18:00:00+02:00"
    assert parse_date("15/11/2026 10:00") == "2026-11-15T10:00:00"
    assert parse_date("15/11/2026") == "2026-11-15"
    assert parse_date("mañana") == ""


def test_find_cadastral_ref():
    assert find_cadastral_ref("REF CATASTRAL 3045301WF3634N0157JY.") == "3045301WF3634N0157JY"
    assert find_cadastral_ref("rc: 3045301 WF3634N 0157 JY") == "3045301WF3634N0157JY"
    assert find_cadastral_ref("nada") == ""


def test_provinces():
    assert province_code("Málaga") == "29"
    assert province_code("malaga provincia") == "29"
    assert province_code("Alicante/Alacant") == "03"
    assert province_code("Vizcaya") == "48"
    assert province_code("7") == "07"
    assert resolve_provinces(["Madrid", "Cádiz"]) == ["28", "11"]
    assert resolve_provinces(["Andalucía"])[:2] == ["04", "11"]
    assert len(resolve_provinces("todas")) == 52
    assert "alacant" in province_slugs("03")
    with pytest.raises(ValueError):
        resolve_provinces(["Atlántida"])


@pytest.mark.parametrize(
    "text,expected",
    [
        # frases reales de fichas del BOE
        ("Tiene una superficie construida de noventa y nueve metros y treinta y cinco decímetros cuadrados", 99.35),
        ("Ocupa una superficie construida de ochenta y cinco metros, sesenta y dos decímetros, todos cuadrados", 85.62),
        ("Tiene una superficie construida de ciento veintinuevo metros y setenta y nueve decimetros", 129.79),
        ("de una superficie de treinta y cinco metros. Linda: Izquierda y fondo", 35.0),
        ("SUPERFICIE TERRENO: CIENTO DOCE METROS CUADRADOS. CONSTRUIDA: NOVENTA Y SIETE METROS CUADRADOS", 97.0),
        ("una superficie edificada de ochenta seis metros treinta y tres decímetros cuadrados", 86.33),
        ("finca de dos mil quinientos metros cuadrados", 2500.0),
        ("DE DOCE METROS DE FRENTE A LA CALLE LARACHE, POR DOCE Y MEDIO DE FONDO", None),
        ("situada a ciento cincuenta metros de la playa", None),
    ],
)
def test_parse_m2_spanish_words(text, expected):
    assert parse_m2(text) == expected


def test_rooms_and_baths_in_words():
    from casascan.textutil import parse_baths

    assert parse_rooms("distribuida en vestíbulo, tres dormitorios, cocina y un baño") == 3
    assert parse_baths("distribuida en vestíbulo, tres dormitorios, cocina y un baño") == 1
    assert parse_baths("salón, cocina y un cuarto de baño") == 1
    assert parse_rooms("Piso de 2 habitaciones") == 2
    assert parse_rooms("Vivienda en planta 3") is None
