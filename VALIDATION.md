# AgentCore Hardware Validation Guide
**Date:** 2026-09-17  
**Purpose:** Step-by-step real hardware validation procedures

---

## 🎯 VALIDATION PHILOSOPHY

**Mocks are NOT proof.**

You must validate:
1. Real microphone captures audio
2. Real STT transcribes speech
3. Real execution happens (browser opens, Android responds)
4. Real observer verifies outcomes
5. Real TTS plays audio
6. Real loop continues (doesn't exit after one cycle)

This guide provides the exact commands and expected outputs for each validation phase.

---

## 📋 PREREQUISITES

### Required Hardware
- ✅ Windows PC/laptop with microphone
- ✅ Working speakers or audio output
- ✅ Internet connection (for TTS and initial STT model download)
- ⚠️ Android phone with USB cable (Phase 4 only)

### Required Software
- Python 3.12.x ONLY (NOT 3.11, NOT 3.13+)
- Git (to check repository state)
- Web browser (Chrome, Edge, or Firefox)

### Required Permissions
- Microphone access for Python
- Speaker/audio output permissions
- Network access (firewall rules)
- Administrator rights (for ADB/Android phase)

---

## 🔍 PHASE 0: ENVIRONMENT VERIFICATION

### Step 1: Check Python Version

**Command:**
```batch
python --version
```

**Expected Output:**
```
Python 3.12.x
```

**❌ If you see 3.11, 3.13, or 3.14:**
AgentCore REQUIRES Python 3.12 ONLY. You must:
1. Uninstall any other Python version (3.11, 3.13, 3.14, etc.)
2. Install Python 3.12 from https://www.python.org/downloads/
3. During install: CHECK "Add Python to PATH"
4. Restart terminal and verify: `python --version` shows 3.12.x

**❌ If you see 2.7.x:**
Python 2 is not supported. Install Python 3.12.

---

### Step 2: Verify Python Location

**Command:**
```batch
where python
```

**Expected Output:**
```
C:\Users\[YourName]\AppData\Local\Programs\Python\Python312\python.exe
```

**Or if .venv exists:**
```
C:\Users\Mayank Bansal\Documents\agentcore\.venv\Scripts\python.exe
C:\Users\[YourName]\AppData\Local\Programs\Python\Python312\python.exe
```

The .venv path should be FIRST (preferred).

**Problem:** If you see multiple Python installations, bootstrap will handle .venv creation.

---

### Step 3: Run Bootstrap

**Command:**
```batch
cd C:\Users\Mayank Bansal\Documents\agentcore
python bootstrap.py
```

**Expected Output:**
```
  AgentCore — readiness report
  ────────────────────────────────────────────────────
  ✓ python          3.12.x (REQUIRED: Python 3.12 ONLY)
  ✓ venv            running inside [path to .venv]
  ✓ dependencies    dependencies ok
  ✓ playwright      chromium already installed
  ✓ workspace       workspace dirs created
  ✓ database        db=present wal=wal integrity=ok migrations=0
  ✓ api_config      providers=[...]
  ✓ tool_registry   15 tools registered
  ⚠ browser_tool    UNAVAILABLE — chromium not launched (optional → BROKEN)
  ⚠ android_tool    UNAVAILABLE — no device connected (optional)
  ✓ network         reachable
  ✓ disk            writable
  ────────────────────────────────────────────────────
  STARTING with optional gaps ⚠ (required checks passed)
```

**✓ All required checks passed** = Continue  
**✗ Any required check failed** = Must fix before proceeding

**Common Issues:**

**Missing dependency:**
```
✗ dependencies    package X not found
```
Fix: Bootstrap should auto-install. If it doesn't:
```batch
python -m pip install -r requirements.txt
```

**Playwright not installed:**
```
✗ playwright      playwright not installed
```
Fix:
```batch
python -m pip install playwright
python -m playwright install chromium
```

**Database corrupt:**
```
✗ database        integrity=not ok
```
Fix: Delete `data/agentcore.db` and re-run bootstrap.

---

### Step 4: Full Health Check

**Command:**
```batch
python main.py doctor
```

**Expected Output:**
```
  AgentCore — dependency health
  ────────────────────────────────────────────────────
  ✓ python         3.12.x
  ✓ dependencies   dependencies ok
  ✓ playwright     chromium already installed
  ✓ workspace      workspace dirs created
  ✓ database       db=present wal=wal integrity=ok migrations=0
  ✓ tools          15 tools registered
  ✓ devices        windows=on, android=off, browser=off
  ✓ dashboard      served at localhost:8000
  ────────────────────────────────────────────────────
  READY ✅
```

**If NOT READY:**
- Fix issues shown in the report
- Each issue includes a "fix:" line
- Re-run `python main.py doctor` after fixes

**Common device states:**
- `windows=on` — always on (built-in)
- `browser=off` — normal until browser actually launches
- `android=off` — normal without USB device connected

---

## 🎤 PHASE 1: FIRST VOICE INTERACTION

**This is the most important test.** If this doesn't work, nothing else matters.

### Prerequisites
- Phase 0 shows READY ✅
- Microphone connected and working
- Speakers connected and working
- Quiet room (minimize background noise)

### Step 1: Launch Voice Runtime

**Command:**
```batch
python main.py voice --loop
```

**Expected Initial Output:**
```
  Voice health:
    ✓ stt           READY      offline model base (loaded once at startup)
    ✓ tts           PACKAGE_READY    edge voice en-US-ChristopherNeural (package available)
    ✓ microphone    READY      [your microphone name]
    ✓ speaker       READY      playback device

🎤 listening…  (speak now)
```

**❌ If you see:**
```
  ✗ stt           MISSING    faster-whisper not installed
      fix: pip install faster-whisper
```
Run the fix command and retry.

**❌ If you see:**
```
  ✗ microphone    UNAVAILABLE    no input device
```
Check:
1. Microphone is connected
2. Windows Privacy Settings → Microphone → Allow desktop apps
3. Device Manager → Audio inputs → Microphone enabled
4. Try: `python -c "import sounddevice; print(sounddevice.query_devices())"`

**❌ If STT is PACKAGE_READY but not READY:**
This means faster-whisper package is installed but the model hasn't loaded yet. First transcription will trigger model download from Hugging Face (may take 1-2 minutes). Continue with Step 2.

---

### Step 2: First Transcription

**With voice runtime running, speak clearly:**
```
"What time is it?"
```

**Expected Output:**
```
🎤 listening…  (speak now)
[After you speak]
🎤 You: what time is it
🤖 The current time is 2:15 PM IST.
[Audio plays from speakers]
🎤 listening…  (speak now)
```

**✅ SUCCESS if:**
1. Your speech was transcribed accurately
2. Agent responded with correct current time
3. Audio played from speakers
4. Prompt returned to "🎤 listening…" (proves loop continues)

**❌ FAILURE: No transcription**
```
🎤 listening…  (speak now)
  (no speech detected — try again)
🎤 listening…  (speak now)
```

**Possible causes:**
1. Microphone not capturing (too quiet)
2. Background noise triggering silence detection too early
3. Wrong microphone selected (if multiple devices)

**Debug:**
```batch
python -c "import sounddevice; sounddevice.rec(16000*5, samplerate=16000, channels=1); sounddevice.wait(); print('Recorded 5 seconds')"
```
If this fails, Python can't access your microphone.

**❌ FAILURE: Model download error**
```
RuntimeError: faster-whisper model load failed: [error]
```

**Likely causes:**
1. No internet connection (model downloads from Hugging Face)
2. Hugging Face cache directory permission issue
3. Antivirus blocking download

**Fix:**
1. Check internet: `ping huggingface.co`
2. Clear cache: Delete `%USERPROFILE%\.cache\huggingface\hub`
3. Disable antivirus temporarily
4. Retry voice command

**❌ FAILURE: Wrong transcription**
```
🎤 You: bottle of milk
```
(You actually said "What time is it?")

**Likely causes:**
1. Background noise
2. Poor microphone quality
3. Microphone too far from mouth
4. Fast speech or accent

**Fixes:**
1. Move closer to microphone (10-15 cm)
2. Speak clearly and slightly slower
3. Use quiet room
4. Test with simple phrase: "Hello AgentCore"

**❌ FAILURE: No audio output**
```
🤖 The current time is 2:15 PM IST.
  🔊 (no audio device — saved to data/tts_cache/[file].mp3)
```

**What happened:**
- TTS synthesis succeeded
- Audio file was created
- Playback failed (no output device or driver issue)

**Check:**
1. Speakers connected and powered
2. Windows volume not muted
3. Correct audio output device selected in Windows
4. Try playing the saved .mp3 manually to verify file is valid

**Fix:**
1. Check Windows Sound settings
2. Set correct default playback device
3. Test: `python -c "import miniaudio; print('miniaudio available')"`
4. Retry voice command

---

### Step 3: Second Interaction (CRITICAL)

**Immediately after the first interaction succeeds, speak again WITHOUT restarting:**

```
"Hello"
```

**Expected Output:**
```
🎤 listening…  (speak now)
🎤 You: hello
🤖 Hello! How can I help you?
[Audio plays]
🎤 listening…  (speak now)
```

**✅ SUCCESS if:**
The second interaction worked without running `python main.py voice --loop` again.

**❌ FAILURE: Process exited**
```
[After first interaction]
C:\Users\Mayank Bansal\Documents\agentcore>
```

Prompt returned to Windows shell instead of "🎤 listening…"

**This is a critical bug.** The persistent loop should continue. Check:
1. `voice/manager.py` line 115-129: `run_loop_async()` should loop
2. `launcher.py` line 129: should call `run_loop_async()` not `run_once_async()`
3. Console for error messages before exit

---

### Step 4: Stop Voice Runtime

**Press Ctrl+C**

**Expected Output:**
```
^C
👋 voice session ended
```

Clean exit, no tracebacks.

---

### Phase 1 Complete

**Mark these items:**
- [ ] `python main.py doctor` showed READY
- [ ] Voice runtime launched without errors
- [ ] STT transcribed first utterance correctly
- [ ] Agent responded with correct time
- [ ] TTS played audio from speakers
- [ ] Voice prompt returned for second interaction
- [ ] Second utterance worked without restart
- [ ] Ctrl+C stopped cleanly

**If all checked:** Phase 1 PASSED ✅  
**If any unchecked:** Phase 1 FAILED ❌ — must fix before Phase 2

---

## 🌐 PHASE 2: WINDOWS BROWSER AUTOMATION

**Prerequisites:**
- Phase 1 PASSED
- Web browser installed (Chrome, Edge, or Firefox)
- Internet connection

### Step 1: Launch Voice Runtime

```batch
python main.py voice --loop
```

Wait for: `🎤 listening… (speak now)`

---

### Step 2: Request Browser Action

**Speak:**
```
"Open YouTube"
```

**Expected Output:**
```
🎤 You: open youtube
[Browser window launches]
[YouTube.com loads]
🤖 Opened YouTube.
[Audio plays]
🎤 listening…  (speak now)
```

**Expected Observations:**
1. **Console shows target resolution:**
   - Target selected: Windows (not Android)
   - Capability: browser/workflow.browser
2. **Browser actually launches:**
   - New browser window appears
   - YouTube.com loads and displays
3. **Observer verification:**
   - Check console for observer logs
   - Should mention "browser detected" or "verification passed"
4. **TTS confirmation:**
   - Audio plays: "Opened YouTube"

**✅ SUCCESS if:**
- YouTube is visible in an open browser
- Console shows Windows was selected
- TTS confirmed success
- Voice continues listening

**❌ FAILURE: Browser didn't open**
```
🎤 You: open youtube
🤖 I tried to open YouTube but encountered an error: [error message]
```

**Check:**
1. Playwright installed: `python -m playwright install chromium`
2. Browser tool health: `python main.py doctor` should show browser_tool status
3. Manual test: `python -c "from playwright.sync_api import sync_playwright; sync_playwright().start().chromium.launch()"`

**❌ FAILURE: Android selected instead of Windows**
```
Target: Android
Reason: [incorrect reason]
```

**This is a target resolution bug.** Check `planning/target_resolver.py`:
- Default should be Windows
- Android only if user says "on my phone" or capability is android-only
- Review: did your utterance contain "phone" or "android"?

**❌ FAILURE: Browser opened but verification failed**
```
[Browser opens YouTube]
🤖 I tried to open YouTube but couldn't verify it opened successfully.
```

**Observer issue.** The tool executed but verification didn't detect success.

**Check:**
1. Is YouTube actually visible?
2. Console logs for observer output
3. `observer/workflow_observers.py` — browser verification logic

**If YouTube IS open but verification failed:**
- Observer logic needs adjustment
- Tool succeeded, verification is too strict

**If YouTube is NOT open:**
- Tool reported success incorrectly
- Need better error detection in browser tool

---

### Step 3: Verify Target Resolution

**Speak (immediately after):**
```
"Open YouTube on my phone"
```

**Expected Output:**
```
🎤 You: open youtube on my phone
🤖 Android device is not connected. Would you like me to open it on Windows instead?
[Or if ADB is available: Android workflow executes]
```

**✅ SUCCESS if:**
- Console shows target resolved to Android (explicit user request)
- If Android unavailable: fallback to Windows clearly stated
- requested_target and actual_target are tracked separately

**Verification:**
This proves target resolver correctly:
1. Parses explicit device requests
2. Distinguishes requested vs actual execution
3. Handles fallback without contaminating session preference

---

### Phase 2 Complete

**Mark these items:**
- [ ] "Open YouTube" selected Windows target
- [ ] Browser actually launched
- [ ] YouTube website actually loaded
- [ ] Observer verified browser opened
- [ ] TTS confirmed success
- [ ] "Open YouTube on my phone" parsed Android request
- [ ] Fallback or Android execution handled correctly

**If all checked:** Phase 2 PASSED ✅  
**If any unchecked:** Phase 2 FAILED ❌

---

## 🔨 PHASE 3: NATIVE EXECUTABLE BUILD

**Prerequisites:**
- Phase 1 PASSED
- Phase 2 PASSED
- All changes committed to git

**⚠️ Important:** Only build the EXE after source validation passes. An EXE with broken source code is useless.

### Step 1: Verify Git Status

```batch
git status
```

**Expected:**
```
On branch main
Your branch is up to date with 'origin/main'.

nothing to commit, working tree clean
```

**If uncommitted changes exist:**
```batch
git add .
git commit -m "fix: multilingual STT config, remove duplicate TTS method, fix voice thread cleanup"
git push
```

---

### Step 2: Run Full Build Pipeline

```batch
build_exe.bat
```

**Expected Output:**
```
============================================
  AGENTCORE.EXE BUILDER
============================================

Using: C:\Users\Mayank Bansal\Documents\agentcore\.venv\Scripts\python.exe
Version: 3.12.x

[setup] Installing dependencies into .venv...

[1/3] Running pre-build verification...
[Verification output]

[1.5/3] Verifying local imports with project Python...
LOCAL IMPORTS OK

[2/3] Starting full build pipeline...

=== [1/7] VERIFY build prerequisites ===
[All checks pass]

=== [2/7] Install dependencies ===
[Pip installs requirements.txt]

=== [3/7] Re-verify after install ===
[All checks pass]

=== [4/7] Run test suites ===
[Architecture tests pass]
[Core tests pass]
[API tests pass]

=== [5/7] PyInstaller --clean ===
[PyInstaller bundles AgentCore.exe]

=== [6/7] Smoke test the built executable ===
SELFCHECK OK — tools=15 db=ok devices=['windows']

=== [7/7] Package build ===
[Creates dist/agentcore-*.zip]

============================================
  BUILD COMPLETE.
  - Executable : dist\AgentCore.exe
  - Package    : dist\agentcore-*.zip
============================================
```

**Build Duration:** ~5-15 minutes depending on system.

**✅ SUCCESS if:**
- All 7 steps completed
- No "[ABORT]" messages
- `dist\AgentCore.exe` exists
- Smoke test passed

**❌ FAILURE at any step:**
Build stops immediately with `[ABORT]` message.

**Common failures:**

**Python version wrong:**
```
[ERROR] AgentCore .venv is using an unsupported Python version
```
Fix: Delete `.venv` folder, run `build_exe.bat` again (will create correct venv).

**Dependencies failed:**
```
[ABORT] Dependency installation FAILED.
```
Check pip error above. Usually network issue or conflicting package.

**Tests failed:**
```
[ABORT] Architecture tests failed
```
Source code has broken tests. Must fix source before building EXE.

**PyInstaller failed:**
```
[ABORT] PyInstaller failed.
```
Check PyInstaller output for missing imports or bundling errors.

**Smoke test failed:**
```
SELFCHECK FAIL — only 3 tools registered
```
EXE bundled incorrectly. Check hidden imports in `build.bat`.

---

### Step 3: Test Native Executable

**Launch the EXE:**
```batch
dist\AgentCore.exe
```

Or double-click `AgentCore.exe` in File Explorer.

**Expected Output:**
```
[Bootstrap output similar to python main.py]

┌──────────────────────────────────────────────┐
│  AgentCore — desktop runtime launcher        │
│  dashboard → http://localhost:8000          │
└──────────────────────────────────────────────┘

[launcher] ✅ runtime ready → http://localhost:8000
[launcher] voice runtime starting…

[voice] health:
[voice] stt: READY - offline model base (loaded once at startup)
[voice] tts: PACKAGE_READY - edge voice en-US-ChristopherNeural
[voice] microphone: READY - [your microphone]
[voice] speaker: READY - playback device

[voice] persistent voice runtime started
[voice] speak naturally — AgentCore is listening
[launcher] opened dashboard in your default browser
[launcher] running in system tray — right-click the icon to stop
```

**Browser should automatically open:** http://localhost:8000

**System tray:** Purple orb icon appears (if pystray installed).

**✅ SUCCESS if:**
- EXE launched without errors
- Dashboard opened in browser
- Voice runtime started (if `voice.enable_on_launch: true`)
- System tray icon appeared
- No console errors

---

### Step 4: Voice Through Native EXE

**With AgentCore.exe running, speak:**
```
"What time is it?"
```

**Expected:**
Same as Phase 1 — voice cycle completes successfully.

**✅ SUCCESS if:**
Voice interaction works identically through the EXE as through `python main.py voice`.

**This proves:** Bundled runtime is functionally identical to source runtime.

---

### Step 5: Stop Native EXE

**Method 1:** Right-click system tray icon → "Stop AgentCore"

**Method 2:** Close console window (if running in console mode)

**Method 3:** Ctrl+C in console

**Expected:**
```
[launcher] Ctrl+C received — shutting down…
[launcher] stopped cleanly
```

Clean exit, no errors.

---

### Phase 3 Complete

**Mark these items:**
- [ ] `build_exe.bat` completed all 7 steps
- [ ] `dist\AgentCore.exe` created successfully
- [ ] EXE launched without errors
- [ ] Dashboard opened in browser
- [ ] Voice runtime started automatically
- [ ] Voice interaction worked through EXE
- [ ] System tray icon appeared
- [ ] Clean shutdown via tray icon

**If all checked:** Phase 3 PASSED ✅  
**If any unchecked:** Phase 3 FAILED ❌

---

## 📱 PHASE 4: ANDROID CONTROL

**Prerequisites:**
- Phase 1 PASSED
- Phase 2 PASSED
- Android phone with USB cable
- USB Debugging enabled on phone

### Step 1: Enable USB Debugging on Android

**On your Android phone:**
1. Settings → About Phone → Tap "Build Number" 7 times
2. Developer Options now appears in Settings
3. Settings → Developer Options → Enable "USB Debugging"
4. Connect phone to PC via USB
5. Phone shows prompt: "Allow USB Debugging?" → Tap "Always allow" + OK

---

### Step 2: Verify ADB Connection

```batch
adb devices
```

**Expected Output:**
```
List of devices attached
[device-id]    device
```

**✅ If you see device listed with "device" status:** Continue.

**❌ If you see "unauthorized":**
```
List of devices attached
[device-id]    unauthorized
```
Phone didn't authorize. Unplug USB, replug, accept prompt on phone.

**❌ If you see no devices:**
```
List of devices attached

```

**Check:**
1. USB cable connected (use original cable if possible)
2. Phone shows "USB Debugging connected" notification
3. Try different USB port
4. Try: `adb kill-server` then `adb start-server` then `adb devices`

**❌ If "adb" command not found:**
ADB not installed or not in PATH.

**Fix for Windows:**
1. Download Android Platform Tools: https://developer.android.com/studio/releases/platform-tools
2. Extract to `C:\platform-tools`
3. Add to PATH: System Properties → Environment Variables → Path → New → `C:\platform-tools`
4. Restart terminal
5. Verify: `adb --version`

---

### Step 3: Test Manual ADB Command

```batch
adb shell am start -a android.intent.action.VIEW -d "https://youtube.com"
```

**Expected:**
YouTube app opens on your phone.

**If this doesn't work:** AgentCore's Android workflow won't work either. Fix ADB connection first.

---

### Step 4: Voice Android Workflow

**Launch AgentCore:**
```batch
python main.py voice --loop
```

**Speak:**
```
"Open YouTube on my phone"
```

**Expected Output:**
```
🎤 You: open youtube on my phone
[Target resolved: Android]
[ADB command sent]
[YouTube opens on phone]
[Screenshot captured]
🤖 Opened YouTube on your Android device.
[Audio plays]
🎤 listening…  (speak now)
```

**Expected Observations:**
1. **Console shows Android target:**
   - Target: Android (explicit user request)
2. **YouTube opens on phone:**
   - YouTube app launches
   - Video feed visible
3. **Observer verification:**
   - Screenshot captured from phone
   - Verification confirms YouTube is open
4. **TTS confirmation:**
   - "Opened YouTube on your Android device"

**✅ SUCCESS if:**
- YouTube actually opened on Android phone
- Console logged ADB execution
- Screenshot captured (check `data/screenshots/`)
- TTS confirmed Android execution

**❌ FAILURE: ADB command failed**
```
🤖 I tried to open YouTube on your phone but encountered an ADB error: [error]
```

**Check:**
1. `adb devices` still shows phone connected
2. Phone didn't go to sleep (screen locked = ADB may timeout)
3. USB Debugging still enabled
4. Try manual ADB command from Step 3

**❌ FAILURE: Windows executed instead of Android**
```
Target: Windows
Reason: android offline; capability exists on windows
```

**Target resolver detected Android unavailable and fell back to Windows.**

**Check:**
1. Is phone actually connected? `adb devices`
2. Device health: `python main.py whoami` → devices should list android=on
3. Did you say "on my phone" clearly?

**❌ FAILURE: YouTube opened but verification failed**
```
[YouTube opens on phone]
🤖 I tried to open YouTube but couldn't verify it opened successfully.
```

**Observer couldn't confirm via screenshot or log inspection.**

**Check:**
1. Is YouTube actually visible on phone?
2. Screenshot exists: `data/screenshots/` folder
3. Observer logic in `observer/workflow_observers.py`

---

### Phase 4 Complete

**Mark these items:**
- [ ] USB Debugging enabled on phone
- [ ] `adb devices` shows phone connected
- [ ] Manual ADB command opened YouTube
- [ ] "Open YouTube on my phone" resolved Android target
- [ ] ADB execution succeeded
- [ ] YouTube actually opened on phone
- [ ] Screenshot captured for verification
- [ ] TTS confirmed Android execution

**If all checked:** Phase 4 PASSED ✅  
**If any unchecked:** Phase 4 FAILED ❌

---

## 🎉 FULL VALIDATION COMPLETE

**If all phases passed:**

✅ Phase 0: Environment ready  
✅ Phase 1: Voice interaction works  
✅ Phase 2: Windows browser automation works  
✅ Phase 3: Native EXE works  
✅ Phase 4: Android control works  

**AgentCore is now VALIDATED on real hardware.**

You can confidently say:
- Voice input works (real microphone)
- STT works (real transcription)
- Agent execution works (real tools)
- Observer verification works (real outcomes)
- TTS works (real audio)
- Windows automation works (real browser)
- Android control works (real device)
- Native EXE works (real packaging)
- Persistent loop works (doesn't exit)

---

## 📊 VALIDATION RESULTS TEMPLATE

**Copy this and fill in your actual results:**

```
=== AGENTCORE HARDWARE VALIDATION RESULTS ===
Date: 2026-09-17
Tester: [Your Name]
System: Windows [version]
Python: [version]

PHASE 0: ENVIRONMENT
[ ] Python version correct (3.12 ONLY)
[ ] Bootstrap completed successfully
[ ] Doctor shows READY
Notes:

PHASE 1: VOICE INTERACTION
[ ] Voice runtime launched
[ ] First transcription accurate
[ ] Agent responded correctly
[ ] TTS played audio
[ ] Second interaction worked (persistent loop)
Transcription accuracy: [Good/Fair/Poor]
TTS audio quality: [Clear/Acceptable/Poor]
Notes:

PHASE 2: WINDOWS AUTOMATION
[ ] "Open YouTube" selected Windows
[ ] Browser actually opened
[ ] YouTube actually loaded
[ ] Observer verified success
[ ] TTS confirmed
Notes:

PHASE 3: NATIVE EXE
[ ] Build completed without errors
[ ] EXE launched successfully
[ ] Voice worked through EXE
[ ] System tray icon appeared
[ ] Clean shutdown
Notes:

PHASE 4: ANDROID CONTROL
[ ] ADB connected to phone
[ ] "Open YouTube on my phone" resolved Android
[ ] YouTube opened on phone
[ ] Screenshot captured
[ ] Verification succeeded
Notes:

OVERALL STATUS:
[ ] ALL PHASES PASSED — AgentCore is VALIDATED
[ ] SOME PHASES FAILED — See notes above

=== END VALIDATION RESULTS ===
```

---

**End of Validation Guide**
