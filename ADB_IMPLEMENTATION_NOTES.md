# ADB Transport Implementation Notes

## Changes Made

### File Modified: `devices/adb.py`

**Key Changes:**
1. **Replaced `adb-shell` library with subprocess-based `adb` CLI**
   - Removed import and usage of `adb_shell.adb_device.AdbDeviceTcp`
   - Implemented `_run_adb()` helper using `subprocess.run()` with shell commands
   - Implemented `_run_adb_shell()` for shell command execution

2. **Added JARVIS-v6 MIT License Attribution**
   - Added MIT License header adapted from JARVIS-v6 by Koay-YH-0102
   - Added at top of file with proper copyright notice

3. **Implemented Real Device Discovery**
   - `connect()` now runs `adb devices -l` to discover real devices
   - Parses output for device serial and state
   - Handles states: `device`, `unauthorized`, `offline`
   - Discovers actual device serial (e.g., `192.168.0.6:40021`) instead of assuming `127.0.0.1:5555`

4. **Backward Compatibility Maintained**
   - Kept `host` and `port` parameters in `__init__` for existing code
   - `health()` still returns host/port for compatibility
   - Device ABC interface intact
   - All existing capabilities preserved

5. **Command Execution Updates**
   - `_shell()` now uses `_run_adb_shell()` with subprocess
   - `_exec_out()` now uses subprocess for binary-safe operations
   - `_input()` unchanged (uses `_shell`)
   - `_cmd_share_file()` updated to use `adb push` via subprocess

## Testing

**Manual Test Results:**
```python
from devices.adb import ADBDevice
dev = ADBDevice()
dev.connect()  # Successfully discovers real device at 192.168.0.6:40021
dev._shell('getprop ro.product.model')  # Returns: 'V2029'
```

**Device Discovery:**
- Successfully finds device at `192.168.0.6:40021`
- Parses device state correctly
- Verifies device responsiveness with ping
- Returns proper health status

## Architecture

The implementation follows JARVIS-v6 `ADBPhoneControl` pattern:
- Subprocess-based `adb` CLI invocation
- Device discovery via `adb devices -l`
- Serial-based command routing via `adb -s <serial>`
- Proper state detection and error handling

## Requirements Met

✅ Replace broken `AdbDeviceTcp(127.0.0.1, 5555)` assumption  
✅ Replace `adb-shell` with `adb` CLI (subprocess)  
✅ Run `adb devices -l` for discovery  
✅ Parse real serial/state (USB, TCP, unauthorized, offline, no-device)  
✅ Support `adb -s <serial>` for commands  
✅ Detect device states  
✅ Keep Device ABC interface intact  
✅ Keep all capabilities/tools intact  
✅ Add MIT license attribution

## Notes

- Host/port parameters retained for config backward compatibility but not used for discovery
- Real device serial is stored in `_dev_serial` attribute
- Serial fallback maintains compatibility with existing code
- All ADB commands now route through real `adb` CLI available at `C:\programs\platform-tools\adb.exe`
