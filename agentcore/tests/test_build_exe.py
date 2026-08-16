"""
Minimal Build Verification Test for AgentCore.exe

This test validates that the packaged executable build can succeed.
Run this on a Windows machine with Python 3.11/3.12.

Usage:
    python tests/test_build_exe.py
"""

import importlib
import subprocess
import sys
from pathlib import Path

# === FIX: Resolve project root correctly ===
# tests/test_build_exe.py → parents[1] = project root
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


CRITICAL_MODULES = [
    "launcher",
    "voice.manager",
    "bs4",
    "requests",
    "fastapi",
    "uvicorn",
    "structlog",
    "sqlalchemy",
]


def is_supported_python() -> bool:
    """AgentCore only supports Python >= 3.11 and < 3.13"""
    return (3, 11) <= sys.version_info[:2] < (3, 13)


def test_python_version():
    """Reject Python 3.13 and 3.14+"""
    print("=== Testing Python Version ===")
    version_str = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    
    if is_supported_python():
        print(f"  ✓ python_version {version_str}")
        return True
    else:
        print(f"  ✗ python_version {version_str} (supported: >= 3.11 and < 3.13)")
        return False


def test_critical_imports():
    """Verify all modules required by the packaged build are importable."""
    print("=== Testing Critical Imports ===")
    failed = []
    for mod in CRITICAL_MODULES:
        try:
            importlib.import_module(mod)
            print(f"  ✓ {mod}")
        except ImportError as e:
            print(f"  ✗ {mod} — {e}")
            failed.append(mod)

    if failed:
        print(f"\n[FAIL] Missing modules: {failed}")
        return False
    print("\n[PASS] All critical imports successful.\n")
    return True


def test_pyinstaller_available():
    """Check if PyInstaller is installed."""
    print("=== Testing PyInstaller ===")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            print(f"  ✓ PyInstaller {result.stdout.strip()}")
            return True
    except Exception as e:
        print(f"  ✗ PyInstaller not available: {e}")
    return False


def test_build_script_exists():
    """Verify build scripts exist."""
    print("=== Checking Build Scripts ===")
    root = Path(__file__).parent.parent
    scripts = ["build.bat", "build_exe.bat"]
    all_exist = True
    for script in scripts:
        path = root / script
        if path.exists():
            print(f"  ✓ {script}")
        else:
            print(f"  ✗ {script} missing")
            all_exist = False
    return all_exist


def test_pytest_collection():
    """Run pytest --collect-only and show real errors if it fails."""
    print("=== Testing Pytest Collection ===")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=120,
        )
        
        if result.returncode == 0:
            print("  ✓ integration  pytest collection passed")
            return True
        else:
            print("  ✗ integration  pytest collect failed")
            print("\n--- Pytest stdout ---")
            print(result.stdout)
            print("\n--- Pytest stderr ---")
            print(result.stderr)
            return False
    except Exception as e:
        print(f"  ✗ pytest collection error: {e}")
        return False


def main():
    print("\nAgentCore.exe Build Verification\n" + "=" * 40 + "\n")

    results = [
        test_python_version(),
        test_critical_imports(),
        test_pyinstaller_available(),
        test_build_script_exists(),
        test_pytest_collection(),
    ]

    print("\n" + "=" * 40)
    if all(results):
        print("✅ BUILD VERIFICATION PASSED")
        print("You can now run: build_exe.bat")
        return 0
    else:
        print("❌ BUILD VERIFICATION FAILED")
        print("Fix the issues above before building AgentCore.exe")
        return 1


if __name__ == "__main__":
    sys.exit(main())