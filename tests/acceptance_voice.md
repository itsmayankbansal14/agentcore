# AgentCore — Real Voice Acceptance Procedure (Windows)

**Purpose**  
Verify the complete personal usage workflow on real Windows hardware:

VOICE → AGENT → EXECUTION → OBSERVATION → VOICE

**Environment**  
- Real Windows 10/11 machine with microphone + speakers
- AgentCore running from source or packaged executable
- Optional: Android device with USB debugging enabled (for phone test)

**Important**  
- These tests must be run on **real hardware**.
- In sandbox/CI environments mark results as **UNVERIFIED**.
- Never claim PASS if the test was only simulated.

---

## TEST A: Deterministic Time Query (No LLM)

**Command**:
```bash
python main.py
```

**Spoken input**:
> "What time is it?"

**Expected behavior**:
1. STT produces accurate transcript → visible in chat history
2. `time_now` tool executes directly (deterministic path)
3. **No LLM call** is made
4. Current time is returned and spoken aloud via TTS

**Pass criteria**:
- [ ] Transcript appears in chat
- [ ] TimeTool executed
- [ ] LLM was NOT called
- [ ] TTS speaks the response

**Result**: ________________ (PASS / FAIL / UNVERIFIED)

---

## TEST B: Windows Browser Target Resolution

**Spoken input**:
> "Open YouTube."

**Expected behavior**:
1. TargetResolver → **Windows + browser**
2. Browser opens YouTube
3. Observer verifies browser state
4. TTS reports success

**Pass criteria**:
- [ ] Correct target (Windows/browser)
- [ ] YouTube actually opened
- [ ] Observer verification succeeded
- [ ] TTS response spoken

**Result**: ________________ (PASS / FAIL / UNVERIFIED)

---

## TEST C: Android Target Resolution

**Spoken input**:
> "Open YouTube on my phone."

**Prerequisites**:
- Android device connected via `adb connect`
- USB debugging enabled

**Expected behavior**:
1. TargetResolver → **Android**
2. ADB executes on phone
3. Observer verifies Android state
4. TTS reports success

**Pass criteria**:
- [ ] Correct target (Android)
- [ ] YouTube launched on phone
- [ ] Observer verification succeeded
- [ ] TTS response spoken

**Result**: ________________ (PASS / FAIL / UNVERIFIED)

> **Note**: If Android is unavailable → mark **UNVERIFIED** or **BLOCKED**. Do not claim PASS.

---

## TEST D: Save Website to Personal Memory

**Spoken input**:
> "Save this website https://example.com. I could use it for X."

**Expected behavior**:
1. WebsiteDiscovery stored in SQLite
2. URL preserved
3. Metadata fetched where possible (no fabrication)
4. Primary purpose and personal usage stored
5. TTS confirms save

**Pass criteria**:
- [ ] Website persisted
- [ ] URL + purpose/usage stored
- [ ] Metadata fetched or marked unavailable
- [ ] TTS confirmation spoken

**Result**: ________________ (PASS / FAIL / UNVERIFIED)

---

## TEST E: Save Idea + Startup Briefing

**Spoken input**:
> "Save this idea: X."

**Expected behavior**:
1. Idea stored in personal memory
2. TTS confirms save
3. Restart AgentCore
4. Startup briefing surfaces the saved item when relevant

**Pass criteria**:
- [ ] Idea persisted
- [ ] TTS confirmation spoken
- [ ] Briefing surfaces the item on restart

**Result**: ________________ (PASS / FAIL / UNVERIFIED)

---

## Summary

| Test | Description                              | Result     | Notes |
|------|------------------------------------------|------------|-------|
| A    | Time query (deterministic, no LLM)       |            |       |
| B    | Open YouTube (Windows)                   |            |       |
| C    | Open YouTube on phone (Android)          |            |       |
| D    | Save website with purpose/usage          |            |       |
| E    | Save idea + startup briefing             |            |       |

**Overall Voice Primary Workflow Status**: ________________

**Date run**: ________________  
**Machine / Environment**: ________________  
**Tester**: ________________

> Any hardware-dependent test that cannot be run must be marked **UNVERIFIED**. Never mark it PASS using mocks.