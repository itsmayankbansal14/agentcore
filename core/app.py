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
from core.plugins import PluginManager
from core.workspace import WorkspaceManager
from executor.recovery import RecoveryPolicy
from tools.health import ToolHealthManager
from database.connection import Database
from devices.adb import ADBDevice
from devices.android import AndroidDevice
from devices.browser import BrowserDevice
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
from tools.local import clipboard as clipboard_tools
from tools.local import filesystem as fs_tools
from tools.workflows import browser_workflow as wf_browser
from tools.workflows import fs_workflow as wf_fs
from tools.workflows import windows_workflow as wf_windows
from tools.workflows import android_workflow as wf_android
from tools.local import knowledge as knowledge_tools
from tools.local import life as life_tools
from tools.storage.todo_storage import SQLiteTodoStorage, TodoStorageProvider
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
        # WorkspaceManager is the single path authority — storage backends
        # request paths through it; nothing hardcodes absolute paths.
        workspace = WorkspaceManager(config.root if config.root else Path(__file__).resolve().parent.parent)
        setup_logging(workspace.logs)
        bind_audit(workspace.logs)
        workspace.clean_tmp()

        db = Database(db_path or str(workspace.db_path()))
        db.create_all()

        bus = EventBus()
        llm = LLMManager(config, bus=bus)
        memory = MemoryManager(db, config, llm=llm)
        from memory.personal import PersonalMemory
        personal = PersonalMemory(db)
        registry = ToolRegistry()

        sandbox = workspace.sandbox
        echo_tools.register_all(registry)
        clipboard_tools.register_all(registry)
        fs_tools.register_all(registry, str(sandbox))
        knowledge_tools.register_all(registry, memory)
        from tools import personal as personal_tools
        personal_tools.register_all(registry, personal, memory=memory)
        todo_provider = TodoStorageProvider(SQLiteTodoStorage(db))
        life_tools.register_all(registry, db, todo_provider=todo_provider)
        # capability workflows (real implementations)
        wf_fs.register_all(registry, sandbox)
        wf_windows.register_all(registry)
        wf_browser.register_all(registry, workspace.screenshots)

        # permissions (confirmation hook is CLI/UI-provided)
        permissions = PermissionManager(config)

        # devices (created before observers/executor so they can reference them)
        devices = DeviceManager()
        win = WindowsDevice(registry)
        win.connect()
        devices.register(win)
        browser_dev = BrowserDevice()
        browser_dev.connect()
        devices.register(browser_dev)
        android = AndroidDevice(fingerprint="unpaired", db=db)
        devices.register(android)
        # REAL ADB transport (vertical slice): adb-shell over TCP (adb connect host:5555)
        adb_host = config.get_str("devices.adb_host", "127.0.0.1")
        adb_port = config.get_int("devices.adb_port", 5555)
        adb = ADBDevice(host=adb_host, port=adb_port)
        devices.register(adb)
        wf_android.register_all(registry, adb)

        # Target Resolution (before planning): intent → device selection
        from planning.target_resolver import TargetResolver
        target_resolver = TargetResolver(devices)
        register_android_tools(registry, devices)

        # vision verifier (LLM vision -> OCR -> pixel diff), real engines
        from vision.verifier import VisionVerifier
        verifier = VisionVerifier(llm=llm, ocr=True)

        # observers (environmental verification) — android observer wired to the device
        observers = default_observers(str(sandbox), android_device=android,
                                      adb_device=adb, verifier=verifier)

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
        from tools.monitor import ToolMonitor
        tool_monitor = ToolMonitor()
        recovery_policy = RecoveryPolicy()
        from planning.direct import DirectToolRouter
        direct_router = DirectToolRouter()
        executor = Executor(db, llm, memory, registry, observers, policy,
                           devices=devices, bus=bus, monitor=tool_monitor,
                           recovery=recovery_policy, workspace=workspace,
                           services={"todo_storage_provider": todo_provider,
                                     "devices": devices, "workspace": workspace},
                           direct_router=direct_router)

        # plugins: auto-discover plugins/ and register their tools (Phase 8)
        plugins = PluginManager(config.root / "plugins")
        plugins.load_all({"registry": registry, "app": None,
                          "db": db, "memory": memory, "devices": devices})

        from agent.task_state import TaskStateStore
        task_state = TaskStateStore(db)
        orchestrator = AgentOrchestrator(config, bus, db, memory, llm, registry,
                                         planner, devices, executor, observers,
                                         permissions, target_resolver=target_resolver,
                                         task_state=task_state)
        app = cls(config, db, bus, memory, llm, registry, planner, devices,
                  orchestrator, executor, observers, permissions, reasoner)
        app.plugins = plugins
        app.tool_monitor = tool_monitor
        app.workspace = workspace
        app.direct_router = direct_router
        app.personal = personal
        app.task_state = task_state
        app.todo_provider = todo_provider
        app.recovery = recovery_policy
        app.tool_health = ToolHealthManager()
        app.tool_health.scan(registry, devices)
        app.target_resolver = target_resolver
        from core.dependencies import DependencyManager
        app.dependency_manager = DependencyManager()
        app.dependency_manager.scan()

        if seed_demo:
            seed_demo_memory(memory)
        return app


def seed_demo_memory(memory: MemoryManager) -> None:
    sid = "demo"
    memory.remember(sid, "identity", "user.name", "Boss", source="seed", confidence=1.0)
    memory.remember(sid, "preference", "location", "Jaipur, India", source="seed", confidence=1.0)
    memory.remember(sid, "preference", "focus", "DSA + projects + life admin", source="seed", confidence=0.9)
