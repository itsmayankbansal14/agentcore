"""AgentCore — core/dependencies.py
DependencyManager — every dependency reports READY / INSTALLING / MISSING /
BROKEN. Startup displays a health report. Never silently fails.

Dependencies: Python, Playwright, ADB, SQLite, OpenRouter (API), Browser,
Filesystem. Optional deps (playwright/adb) degrade to BROKEN without blocking
startup; the report shows the exact fix.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger("agentcore.deps")

ROOT = Path(__file__).resolve().parent.parent

# dependency name -> probe callable returning (present, detail, fix_hint)
_PKG_MODULE = {
    "fastapi": "fastapi", "sqlalchemy": "sqlalchemy", "pydantic": "pydantic",
    "structlog": "structlog", "openai": "openai", "httpx": "httpx",
    "numpy": "numpy", "pypdf": "pypdf", "pystray": "pystray",
    "pillow": "PIL", "watchfiles": "watchfiles", "uvicorn": "uvicorn",
    "websockets": "websockets", "adb-shell": "adb_shell",
    "rapidocr-onnxruntime": "rapidocr_onnxruntime", "psutil": "psutil",
    "playwright": "playwright",
    "pyyaml": "yaml", "pydantic-settings": "pydantic_settings",
    "python-dotenv": "dotenv",
}


def _importable(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def _pip_fix(pkg: str) -> str:
    return f"pip install {pkg}"


@dataclass
class DepStatus:
    name: str
    state: str = "MISSING"       # READY | INSTALLING | MISSING | BROKEN
    detail: str = ""
    fix: str = ""
    optional: bool = False

    def to_dict(self) -> dict:
        return {"name": self.name, "state": self.state, "detail": self.detail,
                "fix": self.fix, "optional": self.optional}


class DependencyManager:
    """Probes + reports the health of every runtime dependency."""

    def __init__(self) -> None:
        self._status: dict[str, DepStatus] = {}
        self.installing: set[str] = set()

    # -- probes -----------------------------------------------------------
    def _probe_python(self) -> DepStatus:
        ok = sys.version_info[:2] >= (3, 11)
        return DepStatus("python",
                         "READY" if ok else "BROKEN",
                         f"{sys.version_info.major}.{sys.version_info.minor}",
                         "install Python 3.11+ from python.org")

    def _probe_sqlite(self) -> DepStatus:
        try:
            import sqlite3
            con = sqlite3.connect(":memory:")
            con.execute("PRAGMA journal_mode=WAL")
            con.close()
            return DepStatus("sqlite", "READY", "WAL supported", "")
        except Exception as e:  # noqa: BLE001
            return DepStatus("sqlite", "BROKEN", str(e)[:80],
                             "install a SQLite-capable Python build")

    def _probe_filesystem(self) -> DepStatus:
        try:
            probe = ROOT / "data" / ".dep_probe"
            probe.parent.mkdir(parents=True, exist_ok=True)
            probe.write_text("x"); probe.unlink()
            return DepStatus("filesystem", "READY", "workspace writable", "")
        except Exception as e:  # noqa: BLE001
            return DepStatus("filesystem", "BROKEN", str(e)[:80],
                             "check data/ permissions")

    def _probe_playwright(self) -> DepStatus:
        if not _importable("playwright"):
            return DepStatus("playwright", "MISSING",
                             "playwright not installed",
                             _pip_fix("playwright") + " && python -m playwright install chromium",
                             optional=True)
        # cheap probe: package + browser marker (never launch chromium here —
        # launching in a scan is slow/racy; doctor does the real launch check)
        marker = ROOT / "data" / ".bootstrap" / "playwright.installed"
        if marker.exists():
            return DepStatus("playwright", "READY", "chromium installed (marker)", "", optional=True)
        return DepStatus("playwright", "BROKEN",
                         "chromium not installed (run doctor for the real launch check)",
                         "python -m playwright install chromium", optional=True)

    def _probe_adb(self) -> DepStatus:
        if shutil.which("adb") is None and not _importable("adb_shell"):
            return DepStatus("adb", "MISSING",
                             "no adb binary and no adb-shell package",
                             "pip install adb-shell (or install platform-tools)",
                             optional=True)
        return DepStatus("adb", "READY", "adb transport available", "", optional=True)

    def _probe_openrouter(self) -> DepStatus:
        try:
            from config.manager import get_config
            key = get_config().get_secret("OPENROUTER_API_KEY") or \
                  get_config().get_secret("OPENAI_API_KEY")
            if key:
                return DepStatus("openrouter", "READY", "API key configured", "")
            return DepStatus("openrouter", "MISSING",
                             "no API key in .env",
                             "add OPENROUTER_API_KEY to .env (openrouter.ai/keys)",
                             optional=True)
        except Exception as e:  # noqa: BLE001
            return DepStatus("openrouter", "BROKEN", str(e)[:80],
                             "check config", optional=True)

    def _probe_browser(self) -> DepStatus:
        pw = self._status.get("playwright")
        if pw is not None and pw.state == "READY":
            return DepStatus("browser", "READY", "chromium runtime", "", optional=True)
        if pw is not None and pw.state == "MISSING":
            return DepStatus("browser", "MISSING", "playwright missing",
                             pw.fix, optional=True)
        return DepStatus("browser", "BROKEN", "chromium not installed",
                         "python -m playwright install chromium", optional=True)

    def _probe_venv(self) -> DepStatus:
        import os
        if getattr(sys, "frozen", False):
            return DepStatus("venv", "READY", "frozen (bundled)", "")
        if os.environ.get("AGENTCORE_IN_VENV") == "1":
            return DepStatus("venv", "READY", f"inside {sys.prefix}", "")
        if _importable("structlog") and _importable("fastapi"):
            return DepStatus("venv", "READY", "deps present (bootstrapped)", "")
        return DepStatus("venv", "MISSING", "not bootstrapped",
                         "run python main.py (auto-creates .venv)")

    # -- scan --------------------------------------------------------------
    def scan(self) -> dict[str, dict]:
        """Evaluate every dependency; never raises."""
        probes = {
            "python": self._probe_python,
            "venv": self._probe_venv,
            "dependencies": lambda: self._probe_dependencies(),
            "playwright": self._probe_playwright,
            "adb": self._probe_adb,
            "sqlite": self._probe_sqlite,
            "openrouter": self._probe_openrouter,
            "browser": self._probe_browser,
            "filesystem": self._probe_filesystem,
        }
        for name, fn in probes.items():
            try:
                self._status[name] = fn()
            except Exception as e:  # noqa: BLE001
                self._status[name] = DepStatus(name, "BROKEN", str(e)[:80], "")
        return {n: s.to_dict() for n, s in self._status.items()}

    def _probe_dependencies(self) -> DepStatus:
        """Aggregate Python-package dependencies."""
        req = ROOT / "requirements.txt"
        if not req.exists():
            return DepStatus("dependencies", "BROKEN", "requirements.txt missing",
                             "restore requirements.txt")
        missing = []
        for line in req.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            pkg = line.split(">=")[0].split("==")[0].split("<")[0].split("[")[0].strip()
            mod = _PKG_MODULE.get(pkg, pkg.replace("-", "_"))
            if not _importable(mod):
                missing.append(pkg)
        if missing:
            return DepStatus("dependencies", "MISSING",
                             "missing: " + ", ".join(missing),
                             "pip install " + " ".join(missing))
        return DepStatus("dependencies", "READY", "all packages present", "")

    # -- helpers -----------------------------------------------------------
    def state(self, name: str) -> str:
        s = self._status.get(name)
        if s is None:
            self.scan()
            s = self._status.get(name)
        return s.state if s else "MISSING"

    def all(self) -> dict[str, dict]:
        return {n: s.to_dict() for n, s in self._status.items()}

    def broken_required(self) -> list[str]:
        """Required (non-optional) deps that are not READY — blocks startup."""
        return [n for n, s in self._status.items()
                if not s.optional and s.state not in ("READY",)]

    def mark_installing(self, name: str) -> None:
        self.installing.add(name)
        self._status.setdefault(name, DepStatus(name, "INSTALLING", "installing…", "")).state = "INSTALLING"
