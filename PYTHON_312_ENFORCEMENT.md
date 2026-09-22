# Python 3.12 STRICT Enforcement — Complete

**Date:** 2026-09-17 09:30 UTC  
**Status:** ✅ COMPLETE

---

## 🎯 REQUIREMENT

**AgentCore requires Python 3.12 ONLY.**

- ✅ Python 3.12.x → ACCEPTED
- ❌ Python 3.11.x → REJECTED
- ❌ Python 3.13.x → REJECTED
- ❌ Python 3.14.x → REJECTED
- ❌ Any other version → REJECTED

---

## ✅ FILES UPDATED

### Core Bootstrap & Validation

**1. `bootstrap.py`**
- Changed from: Range check `(3, 11) <= version < (3, 13)`
- Changed to: Exact check `version == (3, 12)`
- Updated `REQUIRED_PY = (3, 12)` (singular, not range)
- Updated `is_supported_python()` to check exact match only
- Updated `_find_supported_python()` to only search for 3.12
- Updated error messages: "REQUIRED: 3.12.x ONLY"

**2. `validate_env.bat`**
- Updated Python version checks to accept only 3.12
- Rejects 3.11, 3.13, 3.14 with clear error messages
- Updated .venv validation to enforce 3.12

**3. `build_exe.bat`**
- Updated to create .venv with Python 3.12 only
- Uses `py -3.12` exclusively (removed 3.11 fallback)
- Updated error messages: "AgentCore REQUIRES Python 3.12"
- Version check: `sys.version_info[:2] == (3, 12)`

---

### Documentation (13 Files)

**All documentation updated by agent to consistently state "Python 3.12 ONLY":**

1. ✅ `README.md` — Prerequisites section
2. ✅ `STATUS.md` — Python version requirement
3. ✅ `VALIDATION.md` — Phase 0 environment checks
4. ✅ `START_HERE.md` — Quick start requirements
5. ✅ `BUILD_INSTRUCTIONS.md` — Build prerequisites
6. ✅ `CHANGES.md` — Added Python 3.12 enforcement note
7. ✅ `TODO.md` — Python requirement tracking
8. ✅ `AGENTS.md` — Working agreement
9. ✅ `ARCHITECTURE.md` — Startup sequence
10. ✅ `CHANGELOG.md` — Unreleased section
11. ✅ `CONTEXT.md` — Environment facts
12. ✅ `agent_architecture.md` — Tech stack
13. ✅ `REAL_PERSONAL_USAGE_HARDENING.md` — Phase notes

---

## 🔍 VERIFICATION

### How to Verify Python 3.12 Enforcement

**Test 1: Check bootstrap.py**
```python
python -c "from bootstrap import REQUIRED_PY, is_supported_python; print(f'Required: {REQUIRED_PY}'); print(f'3.12 accepted: {is_supported_python()}' if __import__('sys').version_info[:2] == (3,12) else '3.12 rejected')"
```

**Test 2: Try with wrong Python**
```batch
py -3.11 bootstrap.py
```
Expected: Error message stating "Python 3.11 is not supported, use 3.12 only"

**Test 3: Run validation**
```batch
validate_env.bat
```
Expected: Only passes with Python 3.12.x

---

## 📊 BEHAVIOR COMPARISON

### Before (3.11-3.12 Range)

| Python Version | Accepted? |
|----------------|-----------|
| 3.10.x | ❌ Rejected |
| 3.11.x | ✅ Accepted |
| 3.12.x | ✅ Accepted |
| 3.13.x | ❌ Rejected |

### After (3.12 STRICT)

| Python Version | Accepted? |
|----------------|-----------|
| 3.10.x | ❌ Rejected |
| 3.11.x | ❌ Rejected |
| 3.12.x | ✅ Accepted |
| 3.13.x | ❌ Rejected |

---

## 🚨 ERROR MESSAGES

### Bootstrap Error
```
✗ python  3.11.5 (REQUIRED: 3.12.x ONLY) — Python 3.11 is too old, upgrade to 3.12
```

or

```
✗ python  3.13.2 (REQUIRED: 3.12.x ONLY) — Python 3.13 is not supported, use 3.12 only
```

### Build Script Error
```
[ERROR] Python 3.12 not found.
        AgentCore REQUIRES Python 3.12 (not 3.11, not 3.13+).
        Please install Python 3.12 from https://www.python.org/downloads/
```

### Validation Script Error
```
[FAIL] Python 3.11 is NOT supported - AgentCore requires Python 3.12 ONLY
```

---

## 🎯 RATIONALE

### Why Python 3.12 ONLY?

1. **Consistency**: One version eliminates compatibility issues
2. **Modern Features**: Python 3.12 has performance improvements
3. **Testing**: Only need to test against one Python version
4. **Simplicity**: No range checks, no fallback logic
5. **User Clarity**: Clear requirement, no confusion

### Why Not 3.11?

- You requested strict 3.12 enforcement
- Eliminates edge cases between 3.11 and 3.12 differences
- Simpler mental model for users

### Why Not 3.13+?

- Python 3.13+ may have breaking changes
- Not yet validated against AgentCore codebase
- Best practice: stick to stable, tested version

---

## ✅ VALIDATION CHECKLIST

To confirm Python 3.12 enforcement:

- [x] `bootstrap.py` checks exact version (3, 12)
- [x] `validate_env.bat` rejects non-3.12
- [x] `build_exe.bat` uses only `py -3.12`
- [x] All documentation states "3.12 ONLY"
- [x] Error messages are clear and specific
- [x] No fallback to 3.11 anywhere
- [x] No acceptance of 3.13+ anywhere

---

## 🚀 USER IMPACT

### What Users See

**When they have Python 3.12:**
```
✓ python  3.12.5 (REQUIRED: Python 3.12 ONLY)
[Everything works]
```

**When they have Python 3.11:**
```
✗ python  3.11.8 (REQUIRED: Python 3.12 ONLY) — Python 3.11 is too old, upgrade to 3.12

[ERROR] AgentCore .venv is NOT using Python 3.12.
        Delete .venv folder and run this script again to create with Python 3.12.
```

**When they have Python 3.13:**
```
✗ python  3.13.0 (REQUIRED: Python 3.12 ONLY) — Python 3.13 is not supported, use 3.12 only

[ERROR] Python 3.13 is NOT supported - AgentCore requires Python 3.12 ONLY
```

---

## 📝 SUMMARY

**What Changed:**
- Python requirement: `3.11 OR 3.12` → `3.12 ONLY`
- Version check logic: Range check → Exact match
- Error messages: Updated to be explicit about strict requirement
- Documentation: 13 files updated to reflect 3.12 ONLY

**Why It Matters:**
- Eliminates ambiguity
- Simpler codebase
- Clearer user expectations
- Easier to maintain

**Current Status:**
✅ **COMPLETE** — Python 3.12 is now strictly enforced across the entire project.

---

**Last Updated:** 2026-09-17 09:30 UTC  
**Enforced In:** bootstrap.py, validate_env.bat, build_exe.bat, and all documentation
