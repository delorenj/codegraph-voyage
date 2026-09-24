"""Configuration loader for codegraph-voyage.

Supports:
- User-level XDG config: $XDG_CONFIG_HOME/codegraph-voyage/config.toml
  (defaults to ~/.config/codegraph-voyage/config.toml)
- Project-level config: <project_root>/.codegraph/config.toml
- Explicit config path via --config CLI argument or CODEGRAPH_VOYAGE_CONFIG env var.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_FILENAME = "config.toml"
APP_NAME = "codegraph-voyage"


def get_xdg_config_path() -> Path:
    """Return the canonical path to the user-level XDG configuration file."""
    xdg_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_home and xdg_home.strip():
        return Path(xdg_home).expanduser() / APP_NAME / DEFAULT_CONFIG_FILENAME
    return Path.home() / ".config" / APP_NAME / DEFAULT_CONFIG_FILENAME


def get_project_config_path(project_root: str | Path | None = None) -> Path | None:
    """Return the path to project-level configuration file if root is provided."""
    if not project_root:
        return None
    return Path(project_root).resolve() / ".codegraph" / DEFAULT_CONFIG_FILENAME


def parse_simple_toml(content: str) -> dict[str, Any]:
    """Lightweight fallback TOML parser for basic key-value pairs and sections.

    Used when neither tomllib (Python 3.11+) nor tomli is installed.
    Handles string, int, float, bool values, [sections], and comments.
    """
    result: dict[str, Any] = {}
    current_section = result

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Strip trailing comments if not inside quotes
        if "#" in line:
            in_quote = False
            quote_char = None
            comment_idx = -1
            for idx, ch in enumerate(line):
                if ch in ("'", '"'):
                    if not in_quote:
                        in_quote = True
                        quote_char = ch
                    elif quote_char == ch:
                        in_quote = False
                        quote_char = None
                elif ch == "#" and not in_quote:
                    comment_idx = idx
                    break
            if comment_idx >= 0:
                line = line[:comment_idx].strip()
                if not line:
                    continue

        if line.startswith("[") and line.endswith("]"):
            sec_name = line[1:-1].strip()
            current_section = result.setdefault(sec_name, {})
            continue

        if "=" in line:
            key, val_str = line.split("=", 1)
            key = key.strip()
            val_str = val_str.strip()

            if (val_str.startswith('"') and val_str.endswith('"')) or (
                val_str.startswith("'") and val_str.endswith("'")
            ):
                val: Any = val_str[1:-1]
            elif val_str.lower() in ("true", "false"):
                val = val_str.lower() == "true"
            elif val_str.isdigit() or (val_str.startswith("-") and val_str[1:].isdigit()):
                val = int(val_str)
            else:
                try:
                    val = float(val_str)
                except ValueError:
                    val = val_str
            current_section[key] = val

    return result


def parse_toml_file(path: Path) -> dict[str, Any]:
    """Parse a TOML file using tomllib, tomli, or simple fallback parser."""
    try:
        import tomllib  # Python 3.11+
        with open(path, "rb") as f:
            return tomllib.load(f)
    except ImportError:
        try:
            import tomli  # Third-party backport
            with open(path, "rb") as f:
                return tomli.load(f)
        except ImportError:
            with open(path, "r", encoding="utf-8") as f:
                return parse_simple_toml(f.read())


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge override dict on top of base dict recursively."""
    merged = dict(base)
    for k, v in override.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = _deep_merge(merged[k], v)
        else:
            merged[k] = v
    return merged


def load_config(
    config_path: str | Path | None = None,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """Load and merge configuration from XDG, project root, or explicit path.

    Precedence (highest to lowest):
    1. Explicit config_path (if provided) or CODEGRAPH_VOYAGE_CONFIG env var.
    2. Project-level config (.codegraph/config.toml).
    3. User-level XDG config (~/.config/codegraph-voyage/config.toml).
    """
    if config_path:
        path = Path(config_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Configuration file not found: {path}")
        return parse_toml_file(path)

    env_config = os.environ.get("CODEGRAPH_VOYAGE_CONFIG")
    if env_config and env_config.strip():
        path = Path(env_config).expanduser().resolve()
        if path.is_file():
            return parse_toml_file(path)

    config: dict[str, Any] = {}

    # 1. User-level XDG config
    xdg_path = get_xdg_config_path()
    if xdg_path.is_file():
        try:
            config = parse_toml_file(xdg_path)
        except Exception:
            pass

    # 2. Project-level config (overrides user config)
    proj_path = get_project_config_path(project_root)
    if proj_path and proj_path.is_file():
        try:
            proj_config = parse_toml_file(proj_path)
            config = _deep_merge(config, proj_config)
        except Exception:
            pass

    return config
