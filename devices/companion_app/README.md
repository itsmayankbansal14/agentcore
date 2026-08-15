# AgentCore Companion (Android)

The phone-side executor for AgentCore. **No LLM, no memory of its own** — it's a
thin remote hand: connect to the laptop, receive signed commands, execute them,
return results.

## What it does

| Command (from laptop) | Mechanism | Permission needed |
|---|---|---|
| `open_app` / `open_url` / `open_youtube` / `open_whatsapp` / `open_settings` | Intents (`ACTION_VIEW`, launch intents, settings panels) | **none** |
| `read_notifications` | `NotificationListenerService` | **Notification access** (opt-in in Settings) |
| `get_foreground_app` | `UsageStatsManager` | **Usage access** (optional) |
| `clipboard` get/set | `ClipboardManager` | none (small system toast on 13+) |
| `share_file` | FileProvider + chooser | none (SAF picker) |
| `screenshot` | MediaProjection (Phase 6) | **Screen capture**, user-granted per session |

**Privacy posture:** accessibility/UI-control is deliberately NOT in v1; if added
(Phase 6) it stays disabled until the user explicitly enables it.

## Protocol

Mirrors `devices/android.py` exactly:
- Envelope `{v, id, type, device, cmd, params, data, ts, auth:{token}, code}`
- Every message HMAC-SHA256-signed over `id|type|cmd|ts` with the device token
- Phone connects → `hello` (pair code or token) → `paired` → commands (ack + result)
- Heartbeat every 20 s; exponential reconnect backoff

The wire format is **verified by `scripts/phone_sim.py`** and the
`tests/test_android.py` suite — so if the Kotlin app implements `Protocol.kt`
verbatim, it interoperates with the laptop without guesswork.

## Build it (Android Studio)

1. Open this folder (`devices/companion_app`) in Android Studio (Ladybug+).
2. Let Gradle sync (AGP 8.5.2, Kotlin 2.0.20, compileSdk 35).
3. Plug in your phone (enable Developer options + USB debugging) or use an emulator.
4. Run ▶ on `app` — the APK installs, then open the app.

## Pair with your laptop

1. On the laptop run the dashboard: `python main.py serve` (default port 9000).
2. Get a pairing code: `curl -X POST http://localhost:9000/api/devices/pair` →
   `{"pair_code": "123456"}` (valid 2 min).
3. In the app: enter the laptop URL
   (`ws://192.168.1.20:9000/ws/android` — your laptop's LAN IP) + the code.
4. Tap **Connect & Pair**. The app stores the issued token in Keystore-backed
   EncryptedSharedPreferences and reconnects automatically with it afterwards.

> **On the same Wi-Fi** this works directly. For remote use, put the laptop on a
> Tailscale/WireGuard mesh and use the mesh IP — no port forwarding, TLS inside
> the tunnel (design §4.4).

## Permissions setup (after pairing)

- **Notification access**: Settings → Notifications → Notification access →
  enable AgentCore. (Or tap "Open" next to it in the app.)
- **Usage access** (optional): Settings → Security → Usage access → enable.

## Testing without the app

You can simulate a phone entirely in Python:

```bash
# laptop (terminal 1)
python main.py serve
CODE=$(curl -s -X POST http://localhost:9000/api/devices/pair | python3 -c 'import json,sys;print(json.load(sys.stdin)["pair_code"])')

# "phone" (terminal 2)
python scripts/phone_sim.py --pair "$CODE"
```

Then ask the agent (dashboard or `python main.py chat`):
`open whatsapp on my phone` → the sim logs the command and replies.
