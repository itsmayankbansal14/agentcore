"""AgentCore — core/errors.py
Failure taxonomy (requirement 4) + recovery-suggestion generator (requirement 5).

Every failure is classified into one of:
  PlannerFailure · ToolFailure · DeviceFailure · NetworkFailure · APIFailure

`classify(exc, context)` inspects the error string/type and the context
(which component raised it, device name, tool name) and returns a
`FailureInfo` (class + detail). `suggestions_for(info)` returns actionable
recovery suggestions the executor attaches to history and surfaces live.
"""
from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field


class FailureClass(str, enum.Enum):
    PLANNER = "planner"
    TOOL = "tool"
    DEVICE = "device"
    NETWORK = "network"
    API = "api"
    UNKNOWN = "unknown"

    def label(self) -> str:
        return {
            "planner": "Planner failure",
            "tool": "Tool failure",
            "device": "Device failure",
            "network": "Network failure",
            "api": "API failure",
            "unknown": "Unknown failure",
        }[self.value]


@dataclass
class FailureInfo:
    kind: FailureClass
    detail: str
    tool: str = ""
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"class": self.kind.value, "label": self.kind.label(),
                "detail": self.detail, "tool": self.tool,
                "suggestions": self.suggestions}


# ---------------------------------------------------------------------------
# signal patterns
# ---------------------------------------------------------------------------
_DEVICE = re.compile(
    r"device offline|not paired|unpaired|adb|offline|blocked|no android device|"
    r"not connected|device not registered|no adb", re.I)
_NETWORK = re.compile(
    r"connection|connect timeout|timed? ?out|dns|refused|unreachable|"
    r"network|socket|ssl|tls|proxy", re.I)
_API = re.compile(
    r"rate limit|429|401|403|quota|insufficient|authentication|api key|invalid key|"
    r"provider|openrouter|openai|anthropic|gemini|deepseek|model|max_tokens|"
    r"context length|overloaded|5\d\d|bad gateway|service unavailable", re.I)
_PLANNER = re.compile(
    r"decompos|plan|no active plan|subtask|step", re.I)
_TOOL = re.compile(
    r"permission denied|unknown tool|schema|invalid argument|not a file|"
    r"not found|traceback|exception|failed", re.I)


def _match_kind(text: str) -> FailureClass | None:
    if _DEVICE.search(text):
        return FailureClass.DEVICE
    if _NETWORK.search(text):
        return FailureClass.NETWORK
    if _API.search(text):
        return FailureClass.API
    if _PLANNER.search(text):
        return FailureClass.PLANNER
    if _TOOL.search(text):
        return FailureClass.TOOL
    return None


# ---------------------------------------------------------------------------
def classify(exc: BaseException | str, *, component: str = "executor",
             tool: str = "") -> FailureInfo:
    """Classify an exception/error string into a FailureClass with detail.

    `component` hints the source: 'planner', 'tool', 'device', 'llm'/'api',
    'executor'. Specific provider errors (from llm/providers/base) map to API.
    """
    detail = str(exc)
    if isinstance(exc, str):
        detail = exc

    # 1) provider-layer errors → API
    try:
        from llm.providers import (AuthError, ContextOverflowError,
                                   ProviderUnavailableError, RateLimitError)
        if isinstance(exc, (RateLimitError, AuthError, ContextOverflowError,
                            ProviderUnavailableError)):
            return FailureInfo(FailureClass.API, detail, tool=tool)
    except Exception:  # noqa: BLE001
        pass

    # 2) component hint
    if component == "planner":
        return FailureInfo(FailureClass.PLANNER, detail, tool=tool)
    if component == "llm" or component == "api":
        return FailureInfo(FailureClass.API, detail, tool=tool)

    # 3) text/type signal
    kind = _match_kind(detail)
    if kind is None:
        # fall back to exception type
        if isinstance(exc, (TimeoutError,)):
            kind = FailureClass.NETWORK
        elif isinstance(exc, (ValueError, TypeError, KeyError, FileNotFoundError,
                              PermissionError)):
            kind = FailureClass.TOOL
        else:
            kind = FailureClass.UNKNOWN
    return FailureInfo(kind, detail, tool=tool)


# ---------------------------------------------------------------------------
# recovery suggestions (requirement 5)
# ---------------------------------------------------------------------------
_SUGGESTIONS: dict[FailureClass, list[str]] = {
    FailureClass.PLANNER: [
        "Rephrase the goal more concretely (e.g. 'open youtube on my phone').",
        "Break the goal into smaller single-step requests.",
        "Check planner configuration (config/defaults.yaml → planner.*).",
    ],
    FailureClass.TOOL: [
        "Check the tool's arguments — validate required parameters.",
        "Verify the tool's permission level (PermissionManager allow/deny).",
        "Retry once; if persistent, the tool itself may need a fix.",
    ],
    FailureClass.DEVICE: [
        "Ensure the device is connected: adb connect <ip>:5555 (or start the emulator).",
        "Confirm the companion app is paired (pair code from POST /api/devices/pair).",
        "Check device permissions (notification access / accessibility / usage access).",
    ],
    FailureClass.NETWORK: [
        "Check internet connectivity and firewall.",
        "If behind a proxy/VPN, verify it is reachable from this machine.",
        "Retry with backoff — transient network errors often succeed on retry.",
    ],
    FailureClass.API: [
        "Check the API key in .env (OPENROUTER_API_KEY / OPENAI_API_KEY …).",
        "Rate limited? Switch LLM_MODEL to another provider or wait for cooldown.",
        "Add a second provider key — the router fails over automatically.",
    ],
    FailureClass.UNKNOWN: [
        "Inspect the structured log (logs/agentcore.jsonl) for the full trace.",
        "Run python scripts/verify_build.py to check the runtime is healthy.",
        "Re-run with the same goal and watch the live timeline for the failure point.",
    ],
}


def suggestions_for(info: FailureInfo) -> list[str]:
    """Return actionable recovery suggestions for a classified failure."""
    base = list(_SUGGESTIONS.get(info.kind, _SUGGESTIONS[FailureClass.UNKNOWN]))
    # append a device-specific hint when a device tool failed
    if info.kind == FailureClass.DEVICE and info.tool.startswith("android_"):
        base.append("For phone control, the device must be online — check /api/devices.")
    return base
