# AgentCore.exe — Real Hardware Test Checklist

This document contains the required validation steps for `AgentCore.exe` on a real Windows machine.

---

## Pre-Test Requirements

- Windows 10 or 11
- `AgentCore.exe` built using `build_exe.bat`
- Working microphone and speakers
- (Optional) Android device with USB debugging enabled

---

## Test Execution

### 1. Startup

Run `AgentCore.exe` and verify:

- [ ] Executable launches without crashing
- [ ] Dashboard opens at `http://localhost:8000`
- [ ] Voice runtime starts automatically
- [ ] Console shows:
  ```
  [launcher] ✅ runtime ready
  [launcher] voice runtime starting…
  [voice] persistent voice runtime started
  [voice] speak naturally — AgentCore is listening
  ```

### 2. Workflow 1 — Time Query (Deterministic)

**Speak:**
> What time is it?

**Expected:**
- [ ] STT produces transcript
- [ ] TimeTool executes (no LLM call)
- [ ] Response is spoken via TTS
- [ ] AgentCore returns to listening

### 3. Workflow 2 — Windows Browser

**Speak:**
> Open YouTube.

**Expected:**
- [ ] Target resolves to Windows
- [ ] Browser actually opens YouTube
- [ ] Observer verifies browser state
- [ ] Response spoken via TTS
- [ ] Returns to listening

### 4. Workflow 3 — Android (if device available)

**Speak:**
> Open YouTube on my phone.

**Expected:**
- [ ] Target resolves to Android
- [ ] YouTube opens on phone via ADB
- [ ] Observer verifies result
- [ ] Response spoken via TTS
- [ ] Returns to listening

> **Note**: If no Android device is available, mark as **UNVERIFIED**

### 5. Workflow 4 — Save Website

**Speak:**
> Save this website https://example.com. I could use it for X.

**Expected:**
- [ ] Website saved with metadata
- [ ] URL + purpose stored in SQLite
- [ ] Response spoken via TTS

### 6. Workflow 5 — Save Idea + Briefing

**Speak:**
> Save this idea: build a UPI payment announcer.

**Expected:**
- [ ] Idea saved successfully
- [ ] Restart `AgentCore.exe`
- [ ] Startup briefing shows the saved idea

### 7. Failure Resilience (Recommended)

- [ ] Disconnect microphone during a session
- [ ] Voice should report the error but **continue listening**
- [ ] Next voice command should still work

### 8. Dashboard Observation

While voice is active:

- [ ] Open `http://localhost:8000`
- [ ] Confirm it reflects real runtime state (not fake/mock data)

---

## Final Reporting

After completing the tests, report using this format:

```text
Workflow 1 (Time Query):           PASS / FAIL / UNVERIFIED
Workflow 2 (Windows Browser):      PASS / FAIL / UNVERIFIED
Workflow 3 (Android):              PASS / FAIL / UNVERIFIED
Workflow 4 (Save Website):         PASS / FAIL / UNVERIFIED
Workflow 5 (Save Idea):            PASS / FAIL / UNVERIFIED

AgentCore.exe starts voice:        PASS / FAIL
Voice survives failures:           PASS / FAIL
Dashboard remains secondary:       PASS / FAIL

Real Hardware Validation: UNVERIFIED
```

---

**Note**: Do not mark any hardware-dependent workflow as `PASS` unless it was actually tested on real hardware. Use `UNVERIFIED` when testing is not possible.