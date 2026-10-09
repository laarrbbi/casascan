"""Trabajos en segundo plano de la plataforma (búsquedas y diagnósticos).

Solo hay un trabajo a la vez. Mientras corre, los mensajes de log del bot se
copian al trabajo para que la web los muestre en directo.
"""

from __future__ import annotations

import logging
import threading
import traceback
from collections import deque
from collections.abc import Callable
from datetime import datetime
from typing import Any


class _JobLogHandler(logging.Handler):
    def __init__(self, sink: deque):
        super().__init__(level=logging.INFO)
        self.sink = sink
        self.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.sink.append({"nivel": record.levelname.lower(), "texto": self.format(record)})
        except Exception:  # nunca romper el trabajo por el log
            pass


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.job: dict[str, Any] | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self.job and self.job["estado"] == "en_curso")

    def should_stop(self) -> bool:
        return self._stop.is_set()

    def stop(self) -> bool:
        if not self.running:
            return False
        self._stop.set()
        return True

    def start(self, kind: str, target: Callable[[], Any], origin: str = "manual") -> bool:
        """Lanza target() en segundo plano. Devuelve False si ya hay otro trabajo."""
        with self._lock:
            if self.running:
                return False
            self._stop.clear()
            log: deque = deque(maxlen=800)
            self.job = {
                "tipo": kind,
                "origen": origin,
                "estado": "en_curso",
                "inicio": datetime.now().isoformat(timespec="seconds"),
                "fin": None,
                "log": log,
                "resultado": None,
                "error": None,
            }
            job = self.job
            self._thread = threading.Thread(target=self._run, args=(job, target), daemon=True)
            self._thread.start()
            return True

    def _run(self, job: dict, target: Callable[[], Any]) -> None:
        handler = _JobLogHandler(job["log"])
        logger = logging.getLogger("casascan")
        logger.addHandler(handler)
        previous_level = logger.level
        if logger.getEffectiveLevel() > logging.INFO:
            logger.setLevel(logging.INFO)
        try:
            job["resultado"] = target()
            job["estado"] = "detenido" if self._stop.is_set() else "terminado"
        except Exception as exc:
            job["estado"] = "error"
            job["error"] = f"{type(exc).__name__}: {exc}"
            job["log"].append({"nivel": "error", "texto": traceback.format_exc(limit=3)})
        finally:
            job["fin"] = datetime.now().isoformat(timespec="seconds")
            logger.removeHandler(handler)
            logger.setLevel(previous_level)

    def snapshot(self, since: int = 0) -> dict | None:
        """Estado del trabajo actual/último para la web (log desde la línea `since`)."""
        if not self.job:
            return None
        lines = list(self.job["log"])
        out = {k: v for k, v in self.job.items() if k != "log"}
        out["log"] = lines[since:]
        out["log_total"] = len(lines)
        return out

    def wait(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)
