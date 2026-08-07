#!/usr/bin/env python3
"""AgentCore — scripts/verify_build.py
Pre-build verification gate (Phase 3 production readiness).

Checks (each → PASS / FAIL / SKIP / WARN):
  1. python_version   — requires >= 3.11
  2. dependencies     — every dep in pyproject.toml importable
  3. config           — config/defaults.yaml exists (+ .env optional/warn)
  4. assets           — ui/dashboard.html + ui/legacy_jarvis/ present
  5. database         — data/ exists, writable, DB opens + schema builds
  6. git_revision     — OPTIONAL: current commit + branch (skips if no .git)

Usage:
  python scripts/verify_build.py              # human report; exit 1 on any FAIL
  python scripts/verify_build.py --json       # machine-readable JSON report
  python scripts/verify_build.py --skip deps,git   # skip checks by name
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN_PYTHON = (3, 11)

# package-name → import-name for deps that don't import under their pip name
_IMPORT_ALIASES = {
    "pyyaml": "yaml",
    "pydantic-settings": "pydantic_settings",
    "uvicorn": "uvicorn",  # extras ([standard]) still import as uvicorn
    "pillow": "PIL",
    "python-dotenv": "dotenv",
    "beautifulsoup4": "bs4",
}


@dataclass
class Check:
    name: str
    status: str = "PASS"          # PASS | FAIL | SKIP | WARN
    detail: str = ""

    def ok(self) -> bool:
        return self.status in ("PASS", "SKIP", "WARN")


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    env: dict = field(default_factory=dict)

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.checks.append(Check(name=name, status=status, detail=detail))

    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.status == "FAIL"]

    def summary(self) -> str:
        counts: dict[str, int] = {}
        for c in self.checks:
            counts[c.status] = counts.get(c.status, 0) + 1
        return "  · ".join(f"{n}={v}" for n, v in sorted(counts.items())) or "(none)"


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------
def check_python(report: Report) -> None:
    cur = sys.version_info[:2]
    if cur >= MIN_PYTHON:
        report.add("python_version", "PASS",
                   f"{platform.python_version()} (>= {MIN_PYTHON[0]}.{MIN_PYTHON[1]})")
    else:
        report.add("python_version", "FAIL",
                   f"{platform.python_version()} — need >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}")


def load_required_deps() -> list[str]:
    deps: list[str] = []
    pyproject = ROOT / "pyproject.toml"
    if pyproject.exists():
        try:
            import tomllib
            with pyproject.open("rb") as f:
                deps = tomllib.load(f).get("project", {}).get("dependencies", [])
        except Exception:
            pass
    req = ROOT / "requirements.txt"
    if req.exists():
        deps += [l.strip() for l in req.read_text().splitlines()
                 if l.strip() and not l.startswith("#")]
    # normalize: strip version specifiers and extras
    clean = set()
    for d in deps:
        name = d.split(">=")[0].split("==")[0].split("<")[0].strip().split("[")[0]
        if name:
            clean.add(name.lower())
    return sorted(clean)


def import_name(pkg: str) -> str:
    return _IMPORT_ALIASES.get(pkg, pkg.replace("-", "_"))


def check_dependencies(report: Report) -> None:
    required = load_required_deps()
    if not required:
        report.add("dependencies", "WARN", "no pyproject.toml / requirements.txt found")
        return
    missing: list[str] = []
    for pkg in required:
        mod = import_name(pkg)
        if importlib.util.find_spec(mod) is None:
            missing.append(f"{pkg} (import {mod})")
    if missing:
        report.add("dependencies", "FAIL",
                   f"missing: {', '.join(missing)} — run: pip install -r requirements.txt")
    else:
        report.add("dependencies", "PASS", f"{len(required)} deps importable")


def check_config(report: Report) -> None:
    defaults = ROOT / "config" / "defaults.yaml"
    if not defaults.exists():
        report.add("config", "FAIL", f"missing config/defaults.yaml")
        return
    report.add("config", "PASS", "config/defaults.yaml present")
    # .env optional — but warn if absent so user knows they're offline-mode
    env = ROOT / ".env"
    if env.exists():
        report.add("config.env", "PASS", ".env present")
    else:
        report.add("config.env", "WARN",
                   ".env missing — agent runs in offline/mock mode. cp .env.example .env")


def check_assets(report: Report) -> None:
    missing: list[str] = []
    dashboard = ROOT / "ui" / "dashboard.html"
    if not dashboard.exists():
        missing.append("ui/dashboard.html")
    legacy = ROOT / "ui" / "legacy_jarvis"
    if legacy.is_dir():
        n = len(list(legacy.glob("*.html")))
        report.add("assets.legacy", "PASS", f"legacy_jarvis/ ({n} templates)")
    else:
        missing.append("ui/legacy_jarvis/")
    if missing:
        report.add("assets", "FAIL", "missing: " + ", ".join(missing))
    else:
        report.add("assets", "PASS", "ui assets present")


def check_database(report: Report) -> None:
    data_dir = ROOT / "data"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        report.add("database", "FAIL", f"data/ not writable: {e}")
        return
    # writable check
    probe = data_dir / ".write_probe"
    try:
        probe.write_text("x")
        probe.unlink()
    except OSError as e:
        report.add("database", "FAIL", f"data/ not writable: {e}")
        return
    # open a real DB
    try:
        sys.path.insert(0, str(ROOT))
        from database.connection import Database
        db = Database(data_dir / "agentcore.db")
        db.create_all()
        db.close()
        report.add("database", "PASS", f"{db.path.name} opens + schema builds")
    except Exception as e:  # noqa: BLE001
        report.add("database", "FAIL", f"db init failed: {e}")


def check_git(report: Report) -> None:
    git_dir = ROOT / ".git"
    if not git_dir.exists():
        report.add("git_revision", "SKIP", "no .git — not a repository (optional check)")
        return
    try:
        rev = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        branch = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
                                capture_output=True, text=True, timeout=5).stdout.strip()
        report.add("git_revision", "PASS", f"{branch} @ {rev}")
    except Exception as e:  # noqa: BLE001
        report.add("git_revision", "WARN", f"git failed: {e}")


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------
CHECKS = {
    "python": check_python,
    "deps": check_dependencies,
    "config": check_config,
    "assets": check_assets,
    "database": check_database,
    "git": check_git,
}


def verify(skip: list[str] | None = None) -> Report:
    skip = skip or []
    report = Report()
    report.env = {
        "python": platform.python_version(),
        "platform": platform.system(),
        "cwd": str(ROOT),
    }
    for name, fn in CHECKS.items():
        if name in skip:
            report.add(name, "SKIP", "excluded via --skip")
            continue
        try:
            fn(report)
        except Exception as e:  # noqa: BLE001
            report.add(name, "FAIL", f"check raised: {e}")
    return report


def _print_human(report: Report) -> None:
    icons = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️", "WARN": "⚠️"}
    print(f"\n  AgentCore build verification — {report.env['platform']} "
          f"(python {report.env['python']})")
    print("  " + "-" * 56)
    for c in report.checks:
        print(f"  {icons.get(c.status, '·')} {c.name:16s} {c.detail}")
    print("  " + "-" * 56)
    print(f"  summary: {report.summary()}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify AgentCore build prerequisites")
    ap.add_argument("--json", action="store_true", help="emit JSON report")
    ap.add_argument("--skip", default="", help="comma-separated checks to skip")
    args = ap.parse_args()

    skip = [s.strip() for s in args.skip.split(",") if s.strip()]
    report = verify(skip)

    if args.json:
        print(json.dumps({
            "ok": not report.failed(),
            "env": report.env,
            "checks": [c.__dict__ for c in report.checks],
            "summary": report.summary(),
        }, indent=2))
    else:
        _print_human(report)

    return 1 if report.failed() else 0


if __name__ == "__main__":
    sys.exit(main())
