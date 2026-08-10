#!/usr/bin/env python3
"""Read simple ignored local settings without executing shell syntax."""

from __future__ import annotations

import os
from pathlib import Path


DEFAULT_LOCAL_ENV = Path(__file__).resolve().parents[1] / ".env.local"


def local_setting(name: str, default: str = "", path: Path | str = DEFAULT_LOCAL_ENV) -> str:
    """Return an environment value or a literal KEY=VALUE from .env.local."""
    if name in os.environ:
        return os.environ[name]
    target = Path(path)
    if not target.exists():
        return default
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        return value
    return default
