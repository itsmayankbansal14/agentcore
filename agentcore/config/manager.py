"""AgentCore — config/manager.py
Typed, layered configuration. Precedence:
  defaults.yaml < local.yaml (gitignored) < environment < keyring secrets.
Components never read os.environ directly — they ask ConfigManager.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass


class ConfigManager:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or ROOT
        self._data: dict[str, Any] = {}
        self._load(defaults_only=False)

    def _load(self, defaults_only: bool = False) -> None:
        self._data = self._read_yaml(self.root / "config" / "defaults.yaml")
        if not defaults_only:
            local = self.root / "config" / "local.yaml"
            if local.exists():
                self._deep_merge(self._data, self._read_yaml(local))

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        if path.exists():
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return {}

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> None:
        for k, v in override.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                ConfigManager._deep_merge(base[k], v)
            else:
                base[k] = v

    # -- typed getters ------------------------------------------------------
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def get_str(self, dotted: str, default: str = "") -> str:
        v = self.get(dotted, default)
        return str(v) if v is not None else default

    def get_int(self, dotted: str, default: int = 0) -> int:
        try:
            return int(self.get(dotted, default))
        except (TypeError, ValueError):
            return default

    def get_float(self, dotted: str, default: float = 0.0) -> float:
        try:
            return float(self.get(dotted, default))
        except (TypeError, ValueError):
            return default

    def get_bool(self, dotted: str, default: bool = False) -> bool:
        v = self.get(dotted, default)
        return str(v).lower() in ("1", "true", "yes", "on")

    def get_list(self, dotted: str, default: list | None = None) -> list:
        v = self.get(dotted, default)
        return v if isinstance(v, list) else (default or [])

    # -- secrets (env → keyring fallback; never logged) ---------------------
    def get_secret(self, env_key: str, default: str = "") -> str:
        return os.getenv(env_key, default)

    def api_keys(self, provider: str) -> list[str]:
        """All configured keys for a provider (env, then provider keys list)."""
        env_map = {
            "openai": "OPENAI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "claude": "ANTHROPIC_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
        }
        keys: list[str] = []
        env_key = env_map.get(provider)
        if env_key and os.getenv(env_key):
            keys.append(os.getenv(env_key) or "")
        keys += [k for k in self.get_list(f"llm.keys.{provider}", []) if k]
        return keys

    def set_runtime(self, dotted: str, value: Any) -> None:
        """Runtime override (not persisted). Used by /api/config endpoints."""
        parts = dotted.split(".")
        node = self._data
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = value

    def reload(self) -> None:
        self._load(defaults_only=False)

    @property
    def data_dir(self) -> Path:
        p = Path(self.get_str("app.data_dir", "./data"))
        if not p.is_absolute():
            p = self.root / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def log_dir(self) -> Path:
        p = Path(self.get_str("app.log_dir", "./logs"))
        if not p.is_absolute():
            p = self.root / p
        p.mkdir(parents=True, exist_ok=True)
        return p


# module-level singleton (components import this)
_config: ConfigManager | None = None


def get_config() -> ConfigManager:
    global _config
    if _config is None:
        _config = ConfigManager()
    return _config
