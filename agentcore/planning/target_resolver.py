"""AgentCore — planning/target_resolver.py
Target Resolution (before planning).

Pipeline:  User Goal → Intent Analysis → TargetResolver → Planner → Executor → Observer

The TargetResolver answers ONE question: which device should execute this goal?
  - Intent analysis reads the user's words for an explicit target (phone /
    android / mobile / browser / windows / laptop / this pc).
  - Default execution policy: if the user did NOT specify a target, default to
    Windows. Android is only chosen when the user explicitly says phone/android/
    mobile OR Windows cannot satisfy the capability.
  - The Planner NEVER queries Android directly — it requests capabilities
    ("open_youtube", "todo_add", …) and the DeviceManager selects which device
    satisfies them.

The resolver also handles: multi-device (ask once, remember for the session)
and offline fallback (Android offline → fall back to Windows when the
capability exists there; otherwise explain + offer to wait).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger("agentcore.target")


@dataclass
class TargetDecision:
    device: str                  # resolved device: "windows" | "android" | "browser"
    explicit: bool               # user named the target explicitly
    reason: str
    requested_target: str | None = None   # what the user asked for
    actual_target: str | None = None      # what actually executed
    session_preference: str | None = None # remembered preference
    fallback_target: str | None = None    # fallback used (distinct from preference)
    alternative: str | None = None        # legacy field (kept for compatibility)
    ask_user: bool = False           # multiple candidates → ask once
    candidates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "explicit": self.explicit,
            "reason": self.reason,
            "requested_target": self.requested_target,
            "actual_target": self.actual_target,
            "session_preference": self.session_preference,
            "fallback_target": self.fallback_target,
            "alternative": self.alternative,
            "ask_user": self.ask_user,
            "candidates": list(self.candidates),
        }


# ---------------------------------------------------------------------------
# intent analysis
# ---------------------------------------------------------------------------
# explicit target markers in the user's words (strong → weak)
_EXPLICIT = [
    (re.compile(r"\b(on|via|using|through|in)\s+my\s+(phone|android|mobile|device)\b", re.I), "android"),
    (re.compile(r"\b(phone|android|mobile)\b", re.I), "android"),
    (re.compile(r"\b(on|in|via|using)\s+(the\s+)?(browser|chrome|firefox|edge)\b", re.I), "browser"),
    (re.compile(r"\b(browser|chrome|firefox|edge)\b", re.I), "browser"),
    (re.compile(r"\b(on|via|in|using)\s+(the\s+)?(windows|laptop|pc|computer|desktop|this\s+pc)\b", re.I), "windows"),
    (re.compile(r"\b(windows|laptop|pc|desktop)\b", re.I), "windows"),
]

# capability → which device families can satisfy it
_CAPABILITY_DEVICES = {
    "generic": ["windows"],
    "life.todos": ["windows"],
    "life.habits": ["windows"],
    "life.expenses": ["windows"],
    "knowledge": ["windows"],
    "clipboard": ["windows"],
    "workflow.filesystem": ["windows"],
    "workflow.browser": ["windows"],
    "browser": ["windows"],
    "device.android": ["android"],
    "workflow.android": ["android"],
}

_DEVICE_CAPABILITIES = {
    "windows": {"generic", "life.todos", "life.habits", "life.expenses",
                "knowledge", "clipboard", "workflow.filesystem", "workflow.browser"},
    "android": {"device.android", "workflow.android"},
    "browser": {"workflow.browser"},
}


class IntentAnalyzer:
    def explicit_target(self, goal: str) -> tuple[str | None, bool]:
        """Return (device, explicit) — the device the user named, if any."""
        for pattern, device in _EXPLICIT:
            if pattern.search(goal):
                return device, True
        return None, False


class TargetResolver:
    def __init__(self, device_manager) -> None:
        self.devices = device_manager
        self._session_pref: dict[str, str] = {}   # session_id -> remembered device

    # -- device manager facade (never queried directly by the planner) ------
    def available_devices(self) -> dict[str, dict]:
        """Report device health (the dashboard + resolver use this)."""
        out = {}
        for name in ("windows", "android", "browser"):
            dev = self.devices.get(name)
            h = dev.health() if dev else {"online": False}
            caps = dev.capabilities() if dev else []
            out[name] = {"online": h.get("online", False), "health": h,
                         "capabilities": caps}
        return out

    def devices_for_capability(self, capability: str) -> list[str]:
        """Which devices can satisfy a capability (via DeviceManager, not direct
        android queries)."""
        wanted = _CAPABILITY_DEVICES.get(capability, _CAPABILITY_DEVICES["generic"])
        online = []
        for d in wanted:
            dev = self.devices.get(d)
            if dev is not None and dev.health().get("online", False):
                online.append(d)
        if "windows" in wanted:
            online.append("windows")
        return list(dict.fromkeys(online))

    # -- resolution ----------------------------------------------------------
    def resolve(self, goal: str, capability: str, session_id: str) -> TargetDecision:
        analyzer = IntentAnalyzer()
        explicit, is_explicit = analyzer.explicit_target(goal)

        # 1) explicit target
        if explicit is not None:
            return self._select(
                explicit, goal, capability, session_id,
                explicit=True,
                requested_target=explicit,
            )

        # 2) remembered preference for this session
        if session_id in self._session_pref:
            return self._select(
                self._session_pref[session_id], goal, capability, session_id,
                explicit=False,
                remembered=True,
                requested_target=self._session_pref[session_id],
            )

        # 3) capability-only target (android-only capabilities)
        cap_devices = _CAPABILITY_DEVICES.get(capability, _CAPABILITY_DEVICES["generic"])
        android_only = cap_devices == ["android"]

        if android_only:
            return self._select(
                "android", goal, capability, session_id,
                explicit=False,
                reason="capability is android-only",
                requested_target=None,
            )

        # 4) default: windows (generic / browser capabilities)
        return self._select(
            "windows", goal, capability, session_id,
            explicit=False,
            reason="default execution policy (windows)",
            requested_target=None,
        )

    def _select(
        self,
        device: str,
        goal: str,
        capability: str,
        session_id: str,
        *,
        explicit: bool = False,
        remembered: bool = False,
        reason: str = "",
        requested_target: str | None = None,
    ) -> TargetDecision:
        # Normalize requested_target
        requested_target = requested_target or device

        # Android fallback (must not contaminate session preference)
        if device == "android" and not self.devices.get("android").health().get("online"):
            if capability in _DEVICE_CAPABILITIES["windows"] or capability == "generic":
                log.info("android offline -> fallback to windows", goal=goal[:60],
                         capability=capability, session=session_id)
                return TargetDecision(
                    device="windows",
                    explicit=explicit,
                    reason="android offline; capability exists on windows — fell back to windows",
                    requested_target=requested_target,
                    actual_target="windows",
                    session_preference=self._session_pref.get(session_id),
                    fallback_target="windows",
                    alternative=None,
                )
            return TargetDecision(
                device="android",
                explicit=explicit,
                reason="android offline; capability is android-only",
                requested_target=requested_target,
                actual_target="android",
                session_preference=self._session_pref.get(session_id),
                fallback_target=None,
                alternative=None,
            )

        if device == "browser" and not self.devices.get("browser").health().get("online"):
            return TargetDecision(
                device="windows",
                explicit=explicit,
                reason="browser runtime unavailable; using windows host",
                requested_target=requested_target,
                actual_target="windows",
                fallback_target=None,
                alternative="browser",
            )

        if not reason:
            reason = ("explicit user target" if explicit
                      else ("remembered preference for this session" if remembered
                            else "default execution policy (windows)"))

        # Only remember when using the explicit remember() API, not on every task
        # (removed automatic mutation of _session_pref on resolve)

        return TargetDecision(
            device=device,
            explicit=explicit,
            reason=reason,
            requested_target=requested_target,
            actual_target=device,
            session_preference=self._session_pref.get(session_id),
            fallback_target=None,
            alternative=(self._session_pref.get(session_id)
                         if device != self._session_pref.get(session_id)
                         else None),
        )

    def remember(self, session_id: str, device: str) -> None:
        self._session_pref[session_id] = device

    def forget(self, session_id: str) -> None:
        self._session_pref.pop(session_id, None)