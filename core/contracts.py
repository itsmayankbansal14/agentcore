"""AgentCore — core/contracts.py
Normalized, provider-agnostic message/tool types. This is the contract every
other module builds against. The LLM Manager translates to/from these; the
Tool Registry and Planner speak these; the UI/CLI never see provider formats.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


# ---------------------------------------------------------------------------
# LLM layer
# ---------------------------------------------------------------------------
@dataclass
class ToolCall:
    """A structured tool invocation the model requested (function calling)."""
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMMessage:
    """One message in the normalized conversation. Never provider-specific.
    `content` may be a plain string OR a list of OpenAI-style content parts
    (e.g. [{"type":"text","text":...},{"type":"image_url","image_url":{"url": data_uri}}])
    so providers can do real vision."""
    role: Role
    content: str | list | None = None
    tool_calls: list[ToolCall] | None = None   # assistant-only
    tool_call_id: str | None = None            # tool-result-only


@dataclass
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: LLMUsage | None = None
    provider: str = ""
    model: str = ""
    finish_reason: str = ""
    raw: Any = None                            # provider-native object (for debugging)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
class Permission(str, Enum):
    ALWAYS = "always"          # safe: no confirmation
    USER_CONFIRM = "user_confirm"  # ask user before running
    ADMIN = "admin"            # config/system-level


@dataclass
class ToolSpec:
    """JSON-Schema tool declaration, exposed to the LLM for function calling."""
    name: str
    description: str
    parameters: dict[str, Any]                 # JSON Schema object
    capability: str = "generic"                # e.g. "filesystem", "device.android.open_app"
    permission: Permission = Permission.ALWAYS
    idempotent: bool = False


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None
    tool: str = ""
    duration_ms: int = 0
    attempts: int = 1            # how many tries this execution took


# ---------------------------------------------------------------------------
# Events (event bus payloads)
# ---------------------------------------------------------------------------
class EventType(str, Enum):
    USER_MESSAGE_RECEIVED = "user_message_received"
    MESSAGE_ADDED = "message_added"
    PLAN_CREATED = "plan_created"
    PLAN_FAILED = "plan_failed"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    TOOL_STARTED = "tool_started"
    RECOVERY_ATTEMPT = "recovery_attempt"
    RECOVERY_FAILED = "recovery_failed"
    TOOL_RESULT = "tool_result"
    OBSERVER_RESULT = "observer_result"
    PROVIDER_FAILED = "provider_failed"
    PROVIDER_SWITCHED = "provider_switched"
    DEVICE_OFFLINE = "device_offline"
    DEVICE_ONLINE = "device_online"
    SESSION_RESUMED = "session_resumed"
    ERROR = "error"


@dataclass
class Event:
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    ts: float = field(default_factory=time.time)

    def to_log(self) -> dict[str, Any]:
        return {"type": self.type.value, "session": self.session_id, "ts": self.ts, **self.payload}


# ---------------------------------------------------------------------------
# Memory context bundle — what the agent hands the LLM
# ---------------------------------------------------------------------------
@dataclass
class ContextBundle:
    """Assembled context: history window + working memory + LTM facts + knowledge."""
    history: list[LLMMessage] = field(default_factory=list)
    working: dict[str, Any] = field(default_factory=dict)
    ltm_facts: list[str] = field(default_factory=list)
    knowledge: list[str] = field(default_factory=list)
    summary_note: str | None = None
