import base64
import json

import pytest
import yaml

from casascan.config import Config
from casascan.models import Listing
from casascan.sources import SOURCES
from casascan.sources.base import Source
from casascan.storage import Storage
from casascan.web import create_app
from casascan.web.export import export_static


class DemoSource(Source):
    name = "demo"
    label = "Demo"

    def search(self, provinces):
        yield Listing(source="demo", id="1", url="https://x/1", price=90000, surface_m2=70, rooms=2,
                      province_code="28", property_type="vivienda", title="Piso demo")
        yield Listing(source="demo", id="2", url="https://x/2", price=900000, province_code="28",
                      property_type="vivienda", title="Demasiado caro")


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setitem(SOURCES, "demo", DemoSource)
    cfg = {
        "criterios": {"provincias": ["Madrid"], "precio_max": 150000},
        "fuentes": {name: {"activo": False} for name in SOURCES if name != "demo"} | {"demo": {"activo": True}},
        "red": {"pausa_min": 0, "pausa_max": 0},
        "salida": {"carpeta": str(tmp_path / "out"), "base_datos": str(tmp_path / "db.sqlite"), "formatos": ["json"]},
        "enriquecer_catastro": False,
        "notificaciones": {"telegram": {"activo": "auto", "token": "${TELEGRAM_TOKEN}", "chat_id": ""}},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    application = create_app(str(path), scheduler=False)
    application.config["TESTING"] = True
    application.config["CFG_PATH"] = path
    return application


def post(client, url, body=None):
    return client.post(url, data=json.dumps(body or {}), content_type="application/json")


def test_index_and_meta(app):
    c = app.test_client()
    assert c.get("/").status_code == 200
    assert c.get("/static/app.js").status_code == 200
    meta = c.get("/api/meta").get_json()
    assert {"id": "boe", "nombre": SOURCES["boe"].label, "web": SOURCES["boe"].homepage} in meta["fuentes"]
    assert any(p["codigo"] == "29" and p["ccaa"] == "Andalucía" for p in meta["provincias"])


def test_search_job_listings_marks_and_history(app):
    c = app.test_client()
    r = post(c, "/api/busqueda")
    assert r.status_code == 202
    app.extensions["casascan_jobs"].wait(20)
    job = c.get("/api/trabajo").get_json()
    assert job["estado"] == "terminado" and job["resultado"]["encontrados"] == 1
    assert any("Demo" in line["texto"] for line in job["log"])

    items = c.get("/api/inmuebles").get_json()
    assert [i["key"] for i in items] == ["demo:1"]
    assert items[0]["vigente"] and items[0]["is_new"]

    summary = c.get("/api/resumen").get_json()
    assert summary["vigentes"] == 1 and summary["nuevos"] == 1
    assert summary["ultima_busqueda"]["status"] == "ok"

    assert c.post("/api/inmuebles/demo:1/marca", data="marca=favorito").status_code == 415  # no JSON
    assert post(c, "/api/inmuebles/demo:1/marca", {"marca": "favorito", "nota": "ver el lunes"}).status_code == 200
    assert post(c, "/api/inmuebles/demo:1/marca", {"marca": "raro"}).status_code == 400
    item = c.get("/api/inmuebles").get_json()[0]
    assert item["marca"] == "favorito" and item["nota"] == "ver el lunes"
    assert len(c.get("/api/historial").get_json()) == 1


def test_config_edit_keeps_secrets_out(app, monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "secreto-123")
    c = app.test_client()
    conf = c.get("/api/config").get_json()
    assert conf["telegram"]["token"] == "${TELEGRAM_TOKEN}"  # nunca el valor real de la variable
    r = c.put("/api/config", data=json.dumps({
        "criterios": {"provincias": ["Málaga", "Cádiz"], "precio_max": "120000", "tipos": ["vivienda", "local"]},
        "fuentes": {"boe": {"activo": True, "origenes": ["judicial"]}},
        "plataforma": {"auto_horas": 6},
        "telegram": {"chat_id": "42"},
    }), content_type="application/json")
    assert r.status_code == 200
    raw = yaml.safe_load(app.config["CFG_PATH"].read_text(encoding="utf-8"))
    assert raw["criterios"]["precio_max"] == 120000.0
    assert raw["criterios"]["provincias"] == ["Málaga", "Cádiz"]
    assert raw["fuentes"]["boe"] == {"activo": True, "origenes": ["judicial"]}
    assert raw["notificaciones"]["telegram"]["token"] == "${TELEGRAM_TOKEN}"
    assert raw["plataforma"]["auto_horas"] == 6
    bad = c.put("/api/config", data=json.dumps({"criterios": {"provincias": ["Narnia"]}}),
                content_type="application/json")
    assert bad.status_code == 400


def test_password(tmp_path):
    app = create_app(str(tmp_path / "none.yaml"), scheduler=False, password="clave")
    c = app.test_client()
    assert c.get("/").status_code == 401
    auth = base64.b64encode(b"yo:clave").decode()
    assert c.get("/", headers={"Authorization": f"Basic {auth}"}).status_code == 200


def test_static_export_hides_private_marks(tmp_path):
    db = tmp_path / "db.sqlite"
    st = Storage(str(db))
    run = st.start_run(["demo"])
    st.record(Listing(source="demo", id="1", url="https://x/1", price=1000), run_id=run)
    st.finish_run(run, {"demo": [1, 1]}, {}, False, 1, 1)
    st.set_mark("demo:1", estado="favorito", nota="privado")
    st.close()
    out = export_static(Config({"salida": {"base_datos": str(db)}}), str(tmp_path / "web"))
    data = json.loads((out / "data.json").read_text(encoding="utf-8"))
    assert data["meta"]["modo"] == "estatico" and len(data["inmuebles"]) == 1
    assert "nota" not in data["inmuebles"][0] and "marca" not in data["inmuebles"][0]
    assert (out / "index.html").exists() and (out / "static" / "app.js").exists()


def test_rejects_foreign_host_without_password(tmp_path):
    app = create_app(str(tmp_path / "none.yaml"), scheduler=False)
    c = app.test_client()
    assert c.get("/api/meta").status_code == 200  # Host: localhost
    assert c.get("/api/meta", headers={"Host": "evil.example:8000"}).status_code == 403
    assert c.get("/api/meta", headers={"Host": "127.0.0.1:8000"}).status_code == 200
