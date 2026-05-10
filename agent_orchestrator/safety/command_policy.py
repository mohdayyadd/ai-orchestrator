from __future__ import annotations

import re
from typing import Iterable


_BLOCKED_SUBSTRINGS = (
    "rm -rf",
    "git push",
    "git reset --hard",
    "sudo ",
    "chmod -R 777",
    "curl | sh",
    "curl|sh",
    "wget | sh",
    "wget|sh",
    "docker system prune",
    "docker rm -f",
    "docker volume rm",
    "> /dev/sd",
    "mkfs.",
    "dd if=",
)

_BLOCKED_REGEX = (
    re.compile(r"git\s+push\b", re.I),
    re.compile(r"git\s+reset\s+--hard\b", re.I),
)


def is_command_blocked(command: str) -> tuple[bool, str | None]:
    """Return (blocked, reason)."""
    c = command.strip()
    for pat in _BLOCKED_REGEX:
        if pat.search(c):
            return True, f"blocked by policy pattern: {pat.pattern}"
    lowered = c.lower()
    for s in _BLOCKED_SUBSTRINGS:
        if s in lowered:
            return True, f"blocked substring: {s!r}"
    return False, None


def assert_commands_allowed(commands: Iterable[str]) -> None:
    for cmd in commands:
        blocked, reason = is_command_blocked(cmd)
        if blocked:
            raise ValueError(f"Command not allowed: {reason}: {cmd!r}")
