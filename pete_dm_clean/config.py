from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from pete_dm_clean.app_config import AppConfig


def default_config_path() -> Path:
    """
    Resolve the default config file path.

    Order of precedence:
    1) CONFIG_PATH env var (absolute or relative)
    2) ./config.yaml in the current working directory
    """
    env = (os.getenv("CONFIG_PATH") or "").strip()
    return Path(env) if env else Path("config.yaml")


def load_config(path: Path | None) -> dict[str, Any]:
    """
    Load YAML config. If path is None, try CONFIG_PATH env var, then `config.yaml`.
    Returns {} if no config exists.
    """
    if path is None:
        path = default_config_path()
    path = Path(path)
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("config YAML must be a mapping at top level")
    return data


def cfg_get(cfg: dict[str, Any], dotted_key: str, default: Any) -> Any:
    """
    Get nested config value by dotted key, e.g. "build.max_sellers".
    """
    cur: Any = cfg
    for part in dotted_key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def load_validated_config(path: Path | None) -> AppConfig:
    """
    Load YAML config and validate with Pydantic, returning a typed AppConfig.
    If config does not exist, returns defaults.
    """
    data = load_config(path)
    return AppConfig.from_yaml_dict(data)

