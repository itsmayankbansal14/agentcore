# AgentCore.exe Build Instructions

This guide explains how to build `AgentCore.exe` on a Windows machine.

---

## Prerequisites

- Windows 10 or 11
- Python **3.11.x** or **3.12.x** installed
  - During installation, make sure to tick **"Add Python to PATH"**
- At least 4 GB of free disk space

---

## Step-by-Step Build Process

### 1. Copy the Project

Copy the entire `agentcore` folder to your Windows machine.

### 2. Open Command Prompt

Open Command Prompt **inside** the `agentcore` folder.

You can do this by:
- Holding `Shift` + Right-click inside the folder → "Open Command window here", or
- Typing `cmd` in the address bar of File Explorer.

### 3. Run the Build Script

Execute the following command:

```bat
build_exe.bat
```

### 4. What Happens During the Build

The script will automatically:

1. Check for missing dependencies and install them if needed.
2. Run pre-build verification (`tests/test_build_exe.py`).
3. Run the full gated build pipeline (`build.bat`).
4. Use PyInstaller to create `AgentCore.exe`.
5. Place the executable in the `dist` folder.

### 5. Expected Output

If the build succeeds, you should see:

```
dist\AgentCore.exe
```

---

## After Building

### Test the Executable

1. Go to the `dist` folder.
2. Double-click `AgentCore.exe`.
3. Expected behavior:
   - The runtime should start.
   - The dashboard should open in your browser (`http://localhost:8000`).
   - The process should stay alive.

> **Note**: Voice is **not yet connected** in this phase.

---

## Troubleshooting

### "Python not found"

- Reinstall Python 3.11 or 3.12 and make sure **"Add Python to PATH"** is checked.

### Build fails at verification step

- Run this manually first:

```bat
python tests\test_build_exe.py
```

- Fix any missing modules shown.

### PyInstaller fails

- Make sure you are using Python 3.11 or 3.12 (not 3.13+).

---

## Next Phase (After This Works)

Once `AgentCore.exe` successfully starts the runtime and opens the dashboard, the next step will be connecting the **persistent voice runtime**.

---

**Current Status**: Build system prepared and ready for Windows.