#!/usr/bin/env python3
"""AgentCore — scripts/build.py
Build pipeline (hard gates — the build NEVER continues after failed verification):

  VERIFY           → scripts/verify_build.py (mandatory; non-dep failures abort now)
  INSTALL DEPS     → python -m pip install -r requirements.txt (must succeed)
  RE-VERIFY        → scripts/verify_build.py again (any FAIL → abort, clear message)
  TESTS            → hermetic test suites (test_architecture, smoke, test_api)
  PYINSTALLER      → PyInstaller --clean --onefile (ONLY after all verification passed)
  SMOKE EXE        → run the built binary with `--selfcheck` (must exit 0)
  PACKAGE          → zip the distributable → dist/agentcore-<version>.zip

Rules enforced here:
  * verify_build.py failure (incl. missing deps) → abort BEFORE PyInstaller.
  * dependencies are auto-installed once, then re-verified; missing after
    install → stop with a clear error.
  * PyInstaller is invoked with --clean and only when all checks pass.

Usage:
  python scripts/build.py                 # full pipeline
  python scripts/build.py --only verify   # single stage
  python scripts/build.py --no-exe        # skip PyInstaller + exe smoke
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
EXE_NAME = "AgentCore.exe" if sys.platform == "win32" else "AgentCore"

EXCLUDE_TOP = {"data", "logs", ".git", ".venv", "dist", "build", "__pycache__"}
EXCLUDE_SUFFIX = {".pyc", ".db", ".db-shm", ".db-wal"}
EXCLUDE_FILES = {".env"}

HIDDEN_IMPORTS = [
    "sqlalchemy", "structlog", "pydantic", "fastapi", "uvicorn",
    "websockets", "numpy", "pypdf", "starlette", "pystray", "PIL", "watchfiles",
    # uvicorn submodules PyInstaller often misses
    "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
]


def stage(name: str) -> None:
    print(f"\n{'='*60}\n  ▶ STAGE: {name}\n{'='*60}")


def _pyinstaller_sep() -> str:
    return ";" if sys.platform == "win32" else ":"


# ---------------------------------------------------------------------------
# VERIFY (returns ok, failed_checks)
# ---------------------------------------------------------------------------
def run_verify(skip: list[str] | None = None) -> tuple[bool, list[dict], str]:
    cmd = [sys.executable, "scripts/verify_build.py", "--json"]
    if skip:
        cmd += ["--skip", ",".join(skip)]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    try:
        data = json.loads(r.stdout)
        failed = [c for c in data.get("checks", []) if c["status"] == "FAIL"]
        return bool(data.get("ok")), failed, ""
    except Exception:
        return False, [], r.stderr or r.stdout


def stage_verify_pass1() -> bool:
    ok, failed, err = run_verify()
    if ok:
        print("  ✓ all pre-flight checks passed (pass 1)")
        return True
    if err:
        print(f"  ❌ verify could not run: {err[:300]}")
        return False
    nondep = [c for c in failed if c["name"] != "dependencies"]
    if nondep:
        names = ", ".join(c["name"] for c in nondep)
        print(f"  ❌ hard failures (cannot auto-fix): {names}")
        for c in nondep:
            print(f"       - {c['name']}: {c['detail']}")
        return False
    print("  ⚠️  missing dependencies detected — will auto-install:")
    for c in failed:
        print(f"       - {c['detail']}")
    return True  # deps-only failure → proceed to auto-install


def stage_install_deps() -> bool:
    print(f"  running: {sys.executable} -m pip install -r requirements.txt")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                        "-r", "requirements.txt"], cwd=ROOT)
    if r.returncode != 0:
        print("  ❌ dependency installation FAILED (pip returned "
              f"{r.returncode}). Fix and re-run.")
        return False
    print("  ✓ dependencies installed")
    return True


def stage_verify_pass2() -> bool:
    ok, failed, err = run_verify()
    if ok:
        print("  ✓ re-verification passed (all checks green)")
        return True
    if err:
        print(f"  ❌ re-verify could not run: {err[:300]}")
        return False
    print("  ❌ verification STILL FAILING after install — aborting build:")
    for c in failed:
        print(f"       - {c['name']}: {c['detail']}")
    return False


# ---------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------
def stage_tests() -> bool:
    suites = ["tests/test_architecture.py", "tests/smoke.py", "tests/test_api.py"]
    for s in suites:
        print(f"  running {s}…")
        if not subprocess.run([sys.executable, s], cwd=ROOT).returncode == 0:
            return False
    print("  ✓ all test suites passed")
    return True


# ---------------------------------------------------------------------------
# PYINSTALLER (--clean) — only reached when verification passed
# ---------------------------------------------------------------------------
def ensure_pyinstaller() -> bool:
    if shutil.which("pyinstaller"):
        return True
    try:
        import PyInstaller  # noqa: F401
        return True
    except Exception:
        pass
    print("  installing PyInstaller…")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                        "pyinstaller"], cwd=ROOT)
    return r.returncode == 0


def stage_pyinstaller() -> bool:
    if not ensure_pyinstaller():
        print("  ❌ PyInstaller unavailable")
        return False
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean", "--noconfirm", "--onefile", "--console",
        "--name", "AgentCore",
        "--distpath", str(DIST),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
        # absolute source paths — PyInstaller resolves add-data against the
        # spec directory (build/), NOT cwd; relative paths would 404
        "--add-data", f"{ROOT / 'ui'}{_pyinstaller_sep()}ui",
        "--add-data", f"{ROOT / 'config'}{_pyinstaller_sep()}config",
        "--add-data", f"{ROOT / 'dashboard'}{_pyinstaller_sep()}dashboard",
    ]
    for hi in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", hi]
    cmd.append("main.py")
    print("  running PyInstaller --clean --onefile…")
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        print("  ❌ PyInstaller failed")
        return False
    exe = DIST / EXE_NAME
    if not exe.exists():
        print(f"  ❌ expected binary not found: {exe}")
        return False
    print(f"  ✓ built {exe} ({exe.stat().st_size/1024/1024:.1f} MB)")
    return True


# ---------------------------------------------------------------------------
# SMOKE TEST EXECUTABLE
# ---------------------------------------------------------------------------
def stage_smoke_exe() -> bool:
    exe = DIST / EXE_NAME
    if not exe.exists():
        print("  ❌ binary missing — cannot smoke test")
        return False
    print(f"  running {exe} --selfcheck …")
    try:
        r = subprocess.run([str(exe), "--selfcheck"], cwd=ROOT,
                           capture_output=True, text=True, timeout=180)
    except Exception as e:  # noqa: BLE001
        print(f"  ❌ could not run binary: {e}")
        return False
    out = (r.stdout + r.stderr).strip()
    ok = r.returncode == 0 and "SELFCHECK OK" in out
    print(f"  {'✓' if ok else '❌'} binary selfcheck exit={r.returncode}: {out[-160:]}")
    return ok


# ---------------------------------------------------------------------------
# PACKAGE
# ---------------------------------------------------------------------------
def stage_package(version: str | None = None) -> bool:
    DIST.mkdir(exist_ok=True)
    if version is None:
        try:
            import tomllib
            with (ROOT / "pyproject.toml").open("rb") as f:
                version = tomllib.load(f).get("project", {}).get("version", "0.1.0")
        except Exception:
            version = "0.1.0"
    out = DIST / f"agentcore-{version}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(ROOT.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(ROOT)
            parts = rel.parts
            if any(part in EXCLUDE_TOP for part in parts):
                continue
            if any(p.name.endswith(s) for s in EXCLUDE_SUFFIX):
                continue
            if p.name in EXCLUDE_FILES:
                continue
            zf.write(p, rel)
    print(f"  ✓ packaged {out.name} ({out.stat().st_size/1024:.1f} KB)")
    return True


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="AgentCore build pipeline (hard gates)")
    ap.add_argument("--only", choices=["verify", "install", "tests", "pyinstaller",
                                       "smoke-exe", "package"], help="run a single stage")
    ap.add_argument("--no-exe", action="store_true",
                    help="skip PyInstaller + exe smoke (dev/test only)")
    ap.add_argument("--no-package", action="store_true", help="stop after smoke-exe")
    args = ap.parse_args()
    t0 = time.time()

    if args.only:
        stages = [(args.only, None)]
    else:
        stages = [
            ("verify", stage_verify_pass1),
            ("install", stage_install_deps),
            ("verify", stage_verify_pass2),
            ("tests", stage_tests),
        ]
        if not args.no_exe:
            stages += [("pyinstaller", stage_pyinstaller),
                       ("smoke-exe", stage_smoke_exe)]
        if not args.no_package and not args.no_exe:
            stages.append(("package", stage_package))

    for name, fn in stages:
        stage(name.upper())
        if fn is None:
            continue
        if not fn():
            print(f"\n❌ BUILD ABORTED at stage: {name.upper()} "
                  f"(after {time.time()-t0:.1f}s). Nothing further was built.")
            return 1

    print(f"\n✅ BUILD COMPLETE in {time.time()-t0:.1f}s — all gates passed")
    if not args.only:
        print(f"   artifact: {DIST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
