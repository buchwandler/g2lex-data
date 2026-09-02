"""Small dependency-free Git-derived version helper used by setuptools."""

from __future__ import annotations

import os
import re
import subprocess
from email.parser import Parser
from pathlib import Path

_FALLBACK = "0.1.0"
_TAG = re.compile(
    r"^v?(?P<base>\d+\.\d+\.\d+)(?:-(?P<count>\d+)-g(?P<sha>[0-9a-f]+))?(?P<dirty>-dirty)?$"
)


def _sdist_version(root: Path) -> str | None:
    try:
        metadata = Parser().parsestr(
            (root / "PKG-INFO").read_text(encoding="utf-8"), headersonly=True
        )
    except (OSError, UnicodeError):
        return None
    if metadata.get("Name") != "g2lex-data":
        return None
    value = metadata.get("Version")
    return value.strip() if value and value.strip() else None


def get_version() -> str:
    override = os.environ.get("G2LEX_DATA_VERSION")
    if override:
        return override
    root = Path(__file__).resolve().parents[1]
    try:
        text = subprocess.check_output(
            [
                "git",
                "-C",
                str(root),
                "describe",
                "--tags",
                "--long",
                "--dirty",
                "--match",
                "v[0-9]*",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        text = ""
    match = _TAG.match(text)
    if not match:
        return _sdist_version(root) or _FALLBACK
    base = match.group("base")
    count = int(match.group("count") or 0)
    sha = match.group("sha")
    dirty = bool(match.group("dirty"))
    if count == 0 and not dirty:
        return base
    local = []
    if sha:
        local.append(f"g{sha}")
    if dirty:
        local.append("dirty")
    version = f"{base}.post{count}" if count else f"{base}.dev0"
    return version + ("+" + ".".join(local) if local else "")


__version__ = get_version()
