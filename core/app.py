"""AgentCore — core/app.py
Composition root: wires config → db → bus → memory → llm → reasoner → tools
→ permissions → observer → planner → executor → devices → orchestrator.

Ownership (Phase 2):
  - Database sessions: only via `db.session()` context managers (per operation)
  - Executor: the ONLY component that runs tools / the agent loop
  - Planner: only plan/step state; delegates reasoning to the Reasoner
  - Memory: only via MemoryManager (single writer)
  - Tool registry: read-only after bootstrap (register = plugin time)
  - One orchestrator per app; sessions isolate concurrent tasks
"""
from __future__ import annotations

from pathlib import Path

from agent.orchestrator import AgentOrchestrator
from config.manager import ConfigManager, get_config
from core.bus import EventBus
from core.logging import bind_audit, setup_logging
from core.permissions import PermissionManager
from database.connection import Database
from devices.android import AndroidDevice
from devices.base import DeviceManager
from devices.windows import WindowsDevice
from executor.executor import Executor
from executor.policy import ExecutionPolicy
from llm.manager import LLMManager
from memory.manager import MemoryManager
from observer.manager import default_observers
from planner.planner import Planner
from reasoning.base import Reasoner
from reasoning.local_human import HumanReasoner, LocalReasoner
from reasoning.llm import LLMReasoner
from tools.local import echo as echo_tools
from tools.local import filesystem as fs_tools
from tools.local import knowledge as knowledge_tools
from tools.local import life as life_tools
from tools.android_tools import register_all as register_android_tools
from tools.registry import ToolRegistry


def build_reasoner(config: ConfigManager, llm: LLMManager) -> Reasoner:
    """Default: LLM reasoning, falling back to heuristics. Interactive apps can
    inject a HumanReasoner for plan approval."""
    return LLMReasoner(llm)


class AgentApp:
    """Everything the agent needs, assembled. `create()` is the single entry."""

    def __init__(self, config: ConfigManager, db: Database, bus: EventBus,
                 memory: MemoryManager, llm: LLMManager, registry: ToolRegistry,
                 planner: Planner, devices: DeviceManager, orchestrator: AgentOrchestrator,
                 executor: Executor, observers, permissions: PermissionManager,
                 reasoner: Reasoner) -> None:
        self.config = config
        self.db = db
        self.bus = bus
        self.memory = memory
        self.llm = llm
        self.registry = registry
        self.planner = planner
        self.devices = devices
        self.orchestrator = orchestrator
        self.executor = executor
        self.observers = observers
        self.permissions = permissions
        self.reasoner = reasoner

    @classmethod
    def create(cls, root: Path | None = None, db_path: str | None = None,
               seed_demo: bool = True, reasoner: Reasoner | None = None) -> "AgentApp":
        config = ConfigManager(root) if root else get_config()
        setup_logging(config.log_dir)
        bind_audit(config.log_dir)

        db = Database(db_path or (config.data_dir / "agentcore.db"))
        db.create_all()

        bus = EventBus()
        llm = LLMManager(config, bus=bus)
        memory = MemoryManager(db, config, llm=llm)
        registry = ToolRegistry()

        sandbox = config.data_dir / "sandbox"
        sandbox.mkdir(parents=True, exist_ok=True)
        echo_tools.register_all(registry)
        fs_tools.register_all(registry, str(sandbox))
        knowledge_tools.register_all(registry, memory)
        life_tools.register_all(registry, db)

        # permissions (confirmation hook is CLI/UI-provided)
        permissions = PermissionManager(config)

        # devices (created before observers/executor so they can reference them)
        devices = DeviceManager()
        win = WindowsDevice(registry)
        win.connect()
        devices.register(win)
        android = AndroidDevice(fingerprint="unpaired", db=db)
        devices.register(android)
        register_android_tools(registry, devices)

        # observers (environmental verification) — android observer wired to the device
        observers = default_observers(str(sandbox), android_device=android)

        # reasoner for planning
        reasoner = reasoner or build_reasoner(config, llm)
        planner = Planner(db.session_factory, reasoner)

        # executor: owns the loop + policy (devices available in tool ctx)
        policy = ExecutionPolicy(
            max_runtime_s=config.get_float("executor.max_runtime_s", 120.0),
            max_steps=config.get_int("executor.max_steps", 8),
            max_retries=config.get_int("executor.max_retries", 2),
            step_timeout_s=config.get_float("executor.step_timeout_s", 90.0),
            max_tokens=config.get_int("executor.max_tokens", 50_000),
            max_cost=config.get_float("executor.max_cost", 1.0),
            max_recursion_depth=config.get_int("executor.max_recursion_depth", 3),
        )
        executor = Executor(db, llm, memory, registry, observers, policy, devices=devices)

        orchestrator = AgentOrchestrator(config, bus, db, memory, llm, registry,
                                         planner, devices, executor, observers, permissions)
        app = cls(config, db, bus, memory, llm, registry, planner, devices,
                  orchestrator, executor, observers, permissions, reasoner)

        if seed_demo:
            seed_demo_memory(memory)
        return app


def seed_demo_memory(memory: MemoryManager) -> None:
    sid = "demo"
    memory.remember(sid, "identity", "user.name", "Boss", source="seed", confidence=1.0)
    memory.remember(sid, "preference", "location", "Jaipur, India", source="seed", confidence=1.0)
    memory.remember(sid, "preference", "focus", "DSA + projects + life admin", source="seed", confidence=0.9)
