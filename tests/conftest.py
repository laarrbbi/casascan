"""Utilidades de test: fixtures HTML y un cliente HTTP falso (sin red)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

import pytest

from casascan.http import Response

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHttp:
    """Sustituye a HttpClient: responde según una función de enrutado."""

    def __init__(self, route):
        self.route = route
        self.calls: list[tuple[str, str, object]] = []

    def _resp(self, method, url, params=None, data=None, json=None):
        full = url + ("?" + urlencode(params) if params else "")
        self.calls.append((method, full, data if data is not None else json))
        body, status = self.route(method, full, data if data is not None else json)
        if isinstance(body, str):
            body = body.encode("utf-8")
        return Response(url=full, status=status, content=body, headers={}, encoding="utf-8")

    def get(self, url, params=None, **kw):
        return self._resp("GET", url, params=params)

    def post(self, url, data=None, json=None, params=None, **kw):
        return self._resp("POST", url, params=params, data=data, json=json)

    def get_html(self, url, **kw):
        return self._resp("GET", url).text

    def reset_session(self):
        pass

    def close(self):
        pass


@pytest.fixture
def fake_http():
    return FakeHttp
