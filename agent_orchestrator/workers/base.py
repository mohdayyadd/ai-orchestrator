from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass
class WorkerInvocation:
    run_id: str
    worktree_path: Path
    prompt_path: Path
    timeout_seconds: int
    metadata: dict[str, Any]


@dataclass
class WorkerResult:
    exit_code: int
    stdout_path: Path | None
    stderr_path: Path | None
    duration_ms: int


class WorkerAdapter(Protocol):
    kind: str

    def is_enabled(self) -> bool: ...

    def check_available(self) -> tuple[bool, str]: ...

    def run(self, invocation: WorkerInvocation) -> WorkerResult: ...
