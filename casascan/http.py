"""Cliente HTTP con pausas, reintentos, detección de bloqueos y navegador opcional.

- Por defecto usa `requests`.
- Si está instalado `curl_cffi`, se usa para las webs con anti-bot (imita la
  huella TLS de Chrome, lo que ayuda con Fotocasa / Idealista).
- Con `red.navegador: true` (o `--navegador`) las páginas HTML se abren con un
  Chromium real vía Playwright, con un perfil persistente: si una web pide
  captcha, ábrelo en modo visible (`navegador_visible: true`), resuélvelo una
  vez y las siguientes ejecuciones reutilizarán las cookies.
"""

from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

log = logging.getLogger("casascan.http")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
]

# Huellas de páginas de bloqueo / captcha de los anti-bots más comunes.
BLOCK_MARKERS = (
    "captcha-delivery.com",   # DataDome (Idealista); su script normal no lleva este dominio
    "verificación de seguridad",
    "verificaci&#xf3;n de seguridad",
    "please enable js and disable any ad blocker",
    "cf-chl-",                # Cloudflare challenge
    "attention required! | cloudflare",
    "access denied",
    "pardon our interruption",
)


class BlockedError(RuntimeError):
    """La web ha devuelto una página de bloqueo / captcha."""


@dataclass
class Response:
    url: str
    status: int
    content: bytes
    headers: dict[str, str]
    encoding: str | None = None

    @property
    def text(self) -> str:
        enc = self.encoding or "utf-8"
        try:
            return self.content.decode(enc, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        import json

        return json.loads(self.text)


def looks_blocked(status: int, text: str) -> bool:
    if status in (403, 429):
        return True
    head = text[:20000].lower()
    return any(m in head for m in BLOCK_MARKERS)


class HttpClient:
    def __init__(self, net: dict | None = None):
        net = net or {}
        self.delay_min = float(net.get("pausa_min", 2.0))
        self.delay_max = float(net.get("pausa_max", 4.0))
        self.timeout = float(net.get("timeout", 30))
        self.retries = int(net.get("reintentos", 3))
        self.use_browser = bool(net.get("navegador", False))
        self.browser_visible = bool(net.get("navegador_visible", False))
        self.browser_profile = net.get("perfil_navegador", ".casascan_navegador")
        self._browser = None
        self._last_request = 0.0
        self.session = self._new_session()
        self._impersonated = None
        # Registro de peticiones (para el modo diagnóstico) y carpeta donde guardar las páginas
        self.trace: list[dict] = []
        self.snapshot_dir: str | None = net.get("guardar_paginas") or None

    # ------------------------------------------------------------------ util
    def _new_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": random.choice(USER_AGENTS),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.6",
            }
        )
        return s

    def reset_session(self) -> None:
        self.session = self._new_session()
        self._impersonated = None

    def _wait(self) -> None:
        """Pausa aleatoria entre peticiones para no saturar las webs."""
        elapsed = time.monotonic() - self._last_request
        target = random.uniform(self.delay_min, self.delay_max)
        if elapsed < target:
            time.sleep(target - elapsed)
        self._last_request = time.monotonic()

    def _record(self, method: str, url: str, status: int, content: bytes = b"", error: str = "") -> None:
        entry: dict[str, Any] = {"method": method, "url": url, "status": status, "bytes": len(content)}
        if error:
            entry["error"] = error
        if self.snapshot_dir and content:
            folder = Path(self.snapshot_dir)
            folder.mkdir(parents=True, exist_ok=True)
            parts = urlsplit(url)
            stem = re.sub(r"[^a-zA-Z0-9]+", "_", f"{parts.netloc}{parts.path}").strip("_")[:70]
            ext = "json" if content.lstrip()[:1] in (b"{", b"[") else "html"
            name = f"{len(self.trace) + 1:03d}_{stem}.{ext}"
            (folder / name).write_bytes(content)
            entry["file"] = name
        self.trace.append(entry)

    def _impersonating_session(self):
        """Sesión de curl_cffi que imita a Chrome (si está instalado)."""
        if self._impersonated is None:
            try:
                from curl_cffi import requests as cffi_requests  # type: ignore
            except ImportError:
                self._impersonated = False
            else:
                self._impersonated = cffi_requests.Session(impersonate="chrome")
                self._impersonated.headers.update({"Accept-Language": "es-ES,es;q=0.9"})
        return self._impersonated or None

    # --------------------------------------------------------------- request
    def request(
        self,
        method: str,
        url: str,
        *,
        params: Any = None,
        data: Any = None,
        json: Any = None,
        headers: dict | None = None,
        impersonate: bool = False,
        check_block: bool = True,
        encoding: str | None = None,
    ) -> Response:
        last_exc: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self._wait()
            session = self._impersonating_session() if impersonate else None
            session = session or self.session
            try:
                r = session.request(
                    method,
                    url,
                    params=params,
                    data=data,
                    json=json,
                    headers=headers,
                    timeout=self.timeout,
                )
            except Exception as exc:  # requests y curl_cffi lanzan excepciones distintas
                last_exc = exc
                log.warning("Error de red en %s (intento %d/%d): %s", url, attempt, self.retries, exc)
                if attempt == self.retries:
                    self._record(method, url, 0, error=f"{type(exc).__name__}: {str(exc)[:200]}")
                time.sleep(3 * attempt)
                continue
            resp = Response(
                url=str(r.url),
                status=r.status_code,
                content=r.content,
                headers={k.lower(): v for k, v in r.headers.items()},
                encoding=encoding or _guess_encoding(r),
            )
            self._record(method, resp.url, resp.status, resp.content)
            if check_block and looks_blocked(resp.status, resp.text):
                raise BlockedError(
                    f"{url} ha respondido con una página de bloqueo/captcha (HTTP {resp.status})."
                )
            if resp.status >= 500 and attempt < self.retries:
                log.warning("HTTP %d en %s, reintentando…", resp.status, url)
                time.sleep(5 * attempt)
                continue
            return resp
        log.debug("Último error en %s: %r", url, last_exc)
        reason = type(last_exc).__name__ if last_exc else "error"
        if last_exc and "403" in str(last_exc) and "proxy" in str(last_exc).lower():
            reason = "un proxy o cortafuegos de tu red bloquea esta web"
        raise ConnectionError(f"No se pudo descargar {url} ({reason})")

    def get(self, url: str, **kw) -> Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw) -> Response:
        return self.request("POST", url, **kw)

    # --------------------------------------------------------------- browser
    def get_html(self, url: str, *, impersonate: bool = False, wait_selector: str | None = None) -> str:
        """Descarga una página HTML, con navegador real si está activado."""
        if self.use_browser:
            return self._browser_get(url, wait_selector)
        return self.get(url, impersonate=impersonate).text

    def _browser_get(self, url: str, wait_selector: str | None) -> str:
        if self._browser is None:
            self._browser = BrowserFetcher(self.browser_profile, headless=not self.browser_visible)
        self._wait()
        html = self._browser.get(url, wait_selector=wait_selector, timeout=self.timeout)
        self._record("BROWSER", url, 200, html.encode("utf-8"))
        if looks_blocked(200, html):
            raise BlockedError(
                f"{url} pide captcha incluso con navegador. Ejecuta con navegador visible "
                "(--navegador-visible), resuélvelo a mano una vez y vuelve a lanzar."
            )
        return html

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None


def _guess_encoding(r) -> str | None:
    ctype = r.headers.get("content-type", "").lower()
    if "charset=" in ctype:
        return ctype.split("charset=")[-1].split(";")[0].strip() or None
    head = r.content[:2048].lower()
    for enc in (b"iso-8859-15", b"iso-8859-1", b"windows-1252", b"utf-8"):
        if b"charset=" + enc in head or b'charset="' + enc in head:
            return enc.decode()
    return "utf-8"


class BrowserFetcher:
    """Chromium real (Playwright) con perfil persistente."""

    def __init__(self, profile_dir: str, headless: bool = True):
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise RuntimeError(
                "El modo navegador necesita Playwright: pip install playwright && "
                "python -m playwright install chromium"
            ) from exc
        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            profile_dir,
            headless=headless,
            locale="es-ES",
            viewport={"width": 1366, "height": 900},
        )
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

    def get(self, url: str, wait_selector: str | None = None, timeout: float = 30) -> str:
        self._page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        if wait_selector:
            try:
                self._page.wait_for_selector(wait_selector, timeout=timeout * 1000)
            except Exception:  # la página puede no tener resultados
                pass
        else:
            self._page.wait_for_timeout(2500)
        return self._page.content()

    def close(self) -> None:
        try:
            self._ctx.close()
        finally:
            self._pw.stop()
