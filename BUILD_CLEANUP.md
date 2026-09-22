# 🧹 Build Cleanup & Testing Guide

**Date:** 2026-09-17 10:00 UTC  
**Purpose:** Clean unnecessary files and verify build integrity

---

## 🎯 WHAT GETS CLEANED

### Always Removed
- **Python cache**: `__pycache__/`, `*.pyc`, `*.pyo`
- **Build artifacts**: `dist/`, `build/`, `*.spec`
- **Test caches**: `.pytest_cache/`, `.coverage`, `htmlcov/`
- **IDE artifacts**: `.vscode/`, `.idea/`
- **OS files**: `.DS_Store`, `Thumbs.db`, `desktop.ini`
- **Log files**: `logs/`
- **Runtime data**: `data/` (databases, screenshots, caches)
- **Temporary files**: `*.tmp`, `*.temp`, `*.bak`, `*~`

### Optionally Removed
- **Virtual environment**: `.venv/` (you'll be asked)

### Always Kept
- **Source code**: All `*.py` files
- **Configuration**: `config/`
- **Documentation**: All `*.md` files
- **Requirements**: `requirements.txt`
- **Scripts**: All `*.bat` files
- **Core directories**: `core/`, `voice/`, `api/`, etc.

---

## 🚀 QUICK START

### Option 1: Clean + Test (Recommended)
```batch
cd C:\Users\Mayank Bansal\Documents\agentcore
clean_build.bat
test_build.bat
```

### Option 2: Clean Only
```batch
clean_build.bat
```

### Option 3: Test Only (No Cleanup)
```batch
test_build.bat
```

---

## 📋 STEP-BY-STEP CLEANUP

### Step 1: Run Cleanup Script
```batch
cd C:\Users\Mayank Bansal\Documents\agentcore
clean_build.bat
```

**What happens:**
1. Shows what will be removed
2. Asks for confirmation (type `y` to proceed)
3. Removes files in 9 categories
4. Shows summary of removed items

**Expected output:**
```
========================================================
  CLEANUP COMPLETE
========================================================
  Items removed: 15-30 (typical)
  Errors: 0
========================================================
```

---

### Step 2: Verify Build Integrity
```batch
test_build.bat
```

**What it tests:**
1. Essential files present (main.py, bootstrap.py, etc.)
2. No unnecessary files remain
3. Python 3.12 detected
4. Bootstrap can run
5. Doctor check passes
6. Core modules import correctly
7. Configuration is valid

**Expected output:**
```
========================================================
  BUILD INTEGRITY TEST RESULTS
========================================================
  Tests Passed: 20+
  Tests Failed: 0
========================================================

[RESULT] BUILD INTEGRITY: PASSED
```

---

### Step 3: Re-Bootstrap (If .venv Removed)
```batch
python bootstrap.py
```

Only needed if you removed `.venv/` during cleanup.

---

## 🔍 WHAT THE TEST CHECKS

### Test 1: Essential Files Present
Verifies these files exist:
- `main.py`
- `bootstrap.py`
- `launcher.py`
- `requirements.txt`
- `config/defaults.yaml`
- `README.md`
- Core directories (`core/`, `voice/`, `api/`, etc.)

### Test 2: No Unnecessary Files
Confirms these are NOT present:
- `__pycache__/`
- `*.pyc`
- `.vscode/`
- `.idea/`
- `.DS_Store`
- `Thumbs.db`
- `dist/`
- `build/`
- `logs/`
- `data/`

### Test 3: Python Version
- Checks `python --version`
- Must be 3.12.x (strict)

### Test 4: Bootstrap Dry Run
- Runs `python bootstrap.py`
- Verifies no errors

### Test 5: Doctor Health Check
- Runs `python main.py doctor`
- Checks system readiness

### Test 6: Core Module Imports
- Tests: `from core.app import AgentApp`
- Tests: `from voice.manager import VoiceManager`

### Test 7: Configuration Validity
- Checks `stt_language: auto` is present
- Checks old `whisper_model: base.en` is removed

---

## 📊 FILE SIZE REDUCTION

**Before Cleanup:**
- Typical repo size: 50-100 MB (with `.venv`, caches, logs)

**After Cleanup (keeping .venv):**
- Typical repo size: 40-80 MB

**After Cleanup (removing .venv):**
- Source-only repo size: 5-10 MB

---

## ⚠️ COMMON ISSUES

### Issue: "Could not remove data/"
**Cause:** Database or files in use  
**Fix:** Close all AgentCore processes and retry

### Issue: "Could not remove .venv/"
**Cause:** Virtual environment in use  
**Fix:** Close terminals using .venv and retry

### Issue: "Tests failed after cleanup"
**Cause:** Essential files accidentally removed  
**Fix:** Restore from git: `git checkout .`

---

## 🔐 SAFE CLEANUP PRACTICES

### Before Cleanup
1. ✅ Commit all changes to git
2. ✅ Close all running AgentCore processes
3. ✅ Close terminals using `.venv`
4. ✅ Back up any custom data in `data/`

### After Cleanup
1. ✅ Run `test_build.bat` to verify
2. ✅ If .venv removed, run `python bootstrap.py`
3. ✅ Test voice: `python main.py voice --loop`
4. ✅ Verify dashboard: `python main.py serve`

---

## 📦 DISTRIBUTION PREPARATION

### For End Users (Binary Distribution)
1. Run `clean_build.bat` (keep .venv)
2. Run `build_exe.bat` to create `AgentCore.exe`
3. Distribute `dist/agentcore-*.zip`

### For Developers (Source Distribution)
1. Run `clean_build.bat` (remove .venv)
2. Commit cleaned source to git
3. Users run `python bootstrap.py` after clone

---

## 🧪 VERIFICATION CHECKLIST

After cleanup, verify:

- [ ] `test_build.bat` shows "PASSED"
- [ ] `python --version` shows 3.12.x
- [ ] `python bootstrap.py` runs without errors
- [ ] `python main.py doctor` shows "READY ✅"
- [ ] No `__pycache__/` directories remain
- [ ] No `.pyc` files remain
- [ ] Source code files all present
- [ ] Configuration valid (`stt_language: auto`)

---

## 🎯 AUTOMATED WORKFLOW

### Full Clean + Test + Verify
```batch
REM 1. Clean
clean_build.bat

REM 2. Test integrity
test_build.bat
if errorlevel 1 goto :error

REM 3. Re-bootstrap
python bootstrap.py

REM 4. Health check
python main.py doctor
if errorlevel 1 goto :error

echo ✅ Build cleaned and verified!
goto :end

:error
echo ❌ Build verification failed!
exit /b 1

:end
```

---

## 📝 GITIGNORE UPDATE

Updated `.gitignore` now ignores:
- All Python cache files
- Build artifacts
- Test caches
- IDE artifacts
- OS files
- Logs and runtime data
- Virtual environments
- Temporary files
- Hugging Face model cache
- Playwright browser cache

See `.gitignore` for complete list.

---

## ✅ SUCCESS CRITERIA

**Build is clean and ready when:**
1. ✅ `test_build.bat` passes all tests
2. ✅ No warnings about unnecessary files
3. ✅ Bootstrap runs successfully
4. ✅ Doctor shows "READY ✅"
5. ✅ Git status shows only tracked files
6. ✅ File size reduced by removing unnecessary artifacts

---

## 🚨 ROLLBACK PROCEDURE

**If cleanup breaks something:**

```batch
REM Option 1: Restore from git
git status
git checkout .
git clean -fd

REM Option 2: Re-bootstrap
python bootstrap.py
python main.py doctor

REM Option 3: Re-clone
cd ..
git clone <repository-url> agentcore-clean
cd agentcore-clean
python bootstrap.py
```

---

## 📚 RELATED COMMANDS

| Command | Purpose |
|---------|---------|
| `clean_build.bat` | Remove unnecessary files |
| `test_build.bat` | Verify build integrity |
| `python bootstrap.py` | Re-initialize environment |
| `python main.py doctor` | Health check |
| `build_exe.bat` | Create native executable |
| `git clean -fdx` | Nuclear clean (removes EVERYTHING) |

---

## 🎉 READY TO DISTRIBUTE

After successful cleanup and testing:

**For binary distribution:**
1. ✅ Build is clean
2. ✅ Tests pass
3. ✅ Run `build_exe.bat`
4. ✅ Distribute `dist/agentcore-*.zip`

**For source distribution:**
1. ✅ Build is clean
2. ✅ Tests pass
3. ✅ Commit to git
4. ✅ Push to repository

**The build is now production-ready!** 🚀

---

**Last Updated:** 2026-09-17 10:00 UTC  
**Scripts:** clean_build.bat, test_build.bat  
**Next Action:** Run `clean_build.bat` then `test_build.bat`
