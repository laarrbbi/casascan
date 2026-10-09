from types import SimpleNamespace
from urllib.parse import urlencode

from conftest import load
from test_boe import _route as boe_route

from casascan.config import Config
from casascan.diagnose import format_report, page_hints, run_diagnostics
from casascan.http import HttpClient


class FakeSession:
    """Imita a requests.Session para probar el HttpClient real (con su registro)."""

    def __init__(self, route):
        self.route = route
        self.headers = {}

    def request(self, method, url, params=None, data=None, json=None, headers=None, timeout=None):
        full = url + ("?" + urlencode(params) if params else "")
        body, status = self.route(method, full, data)
        return SimpleNamespace(url=full, status_code=status, content=body.encode("utf-8"),
                               headers={"content-type": "text/html; charset=utf-8"})


def route(method, url, data):
    if "idealista" in url:
        return '<html><script src="https://geo.captcha-delivery.com/x.js"></script></html>', 403
    return boe_route(method, url, data)


def factory(net):
    client = HttpClient({**net, "pausa_min": 0, "pausa_max": 0})
    client.session = FakeSession(route)
    client._impersonated = False
    return client


def test_page_hints():
    h = page_hints(load("boe_resultados_p1.html"))
    assert h["li.resultado-busqueda"] == 2 and "bloqueo" not in h
    g = page_hints(load("boe_general_265489.html"))
    assert "Valor subasta" in g["th"] and "Tasación" in g["th"]
    j = page_hints(load("boe_sumario.json"))
    assert j["tipo"] == "json" and j["claves"] == ["status", "data"]


def test_run_diagnostics(tmp_path):
    cfg = Config({"criterios": {"provincias": ["04"], "tipos": ["vivienda"]}, "fuentes": {"boe": {"estados": ["EJ"]}}})
    results = run_diagnostics(cfg, ["boe", "idealista"], "04", tmp_path, http_factory=factory)
    boe, idealista = results
    assert boe["error"] == "" and boe["resultados"] == 1  # 1 página; la multipropiedad se excluye
    first = boe["peticiones"][0]
    assert first["method"] == "POST" and first["status"] == 200
    assert (tmp_path / "boe" / first["file"]).exists()
    assert first["pistas"]["li.resultado-busqueda"] == 2
    assert idealista["error"].startswith("BLOQUEO")
    assert idealista["peticiones"][0]["status"] == 403 and idealista["peticiones"][0]["pistas"]["bloqueo"]
    text = format_report(results)
    assert "✓" in text and "✗ BLOQUEO" in text and "th: Identificador" in text
