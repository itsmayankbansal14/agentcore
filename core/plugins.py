"""AgentCore — core/plugins.py
Plugin system (Phase 8). Plugins live in `plugins/` (one module per plugin)
and optionally expose a `register(registry, ctx)` function that adds tools /
memory hooks. The plugin manager also supports setuptools entry points.

A plugin is a plain module:
    # plugins/my_plugin.py
    def register(registry, ctx):
        registry.register(MyTool())

Adding a plugin = dropping a file in plugins/ + restart. No core changes.
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any, Callable

import structlog

from tools.registry import ToolRegistry

log = structlog.get_logger("agentcore.plugins")


class PluginManager:
    def __init__(self, plugins_dir: str | Path | None = None) -> None:
        self.plugins_dir = Path(plugins_dir) if plugins_dir else None
        self.loaded: list[str] = []

    def discover(self) -> list[str]:
        """Plugin module names found in the plugins directory."""
        if self.plugins_dir is None or not self.plugins_dir.is_dir():
            return []
        return sorted(p.stem for p in self.plugins_dir.glob("*.py")
                      if p.name != "__init__.py" and not p.name.startswith("_"))

    def load_plugin(self, name: str, ctx: dict[str, Any]) -> bool:
        """Import a plugin module and call its register(registry, ctx)."""
        if self.plugins_dir is None:
            return False
        try:
            import sys
            if str(self.plugins_dir.resolve()) not in sys.path:
                sys.path.insert(0, str(self.plugins_dir.resolve()))
            mod = importlib.import_module(name)
            fn: Callable | None = getattr(mod, "register", None)
            if fn is None:
                log.warning("plugin has no register()", plugin=name)
                return False
            fn(ctx.get("registry"), ctx)
            self.loaded.append(name)
            log.info("plugin loaded", plugin=name)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("plugin failed to load", plugin=name, error=str(e))
            return False

    def load_all(self, ctx: dict[str, Any]) -> list[str]:
        """Load every discovered plugin. Returns successfully loaded names."""
        for name in self.discover():
            self.load_plugin(name, ctx)
        return self.loaded
