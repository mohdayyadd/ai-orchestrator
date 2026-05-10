from __future__ import annotations

from agent_orchestrator.settings import Settings
from agent_orchestrator.workers.base import WorkerAdapter
from agent_orchestrator.workers.claude_codex_cursor import ClaudeCodeWorker, CodexWorker, CursorWorker
from agent_orchestrator.workers.mock_worker import MockWorker


def get_worker(kind: str, settings: Settings) -> WorkerAdapter:
    k = kind.lower().strip()
    if k == "mock":
        return MockWorker()
    if k == "claude":
        return ClaudeCodeWorker(
            settings.claude_code_bin,
            settings.claude_code_extra_args,
            enabled=settings.enable_claude_worker,
            running_in_docker=settings.running_in_docker,
            allow_in_docker=settings.allow_cli_workers_in_docker,
        )
    if k == "codex":
        return CodexWorker(
            settings.codex_bin,
            settings.codex_extra_args,
            enabled=settings.enable_codex_worker,
            running_in_docker=settings.running_in_docker,
            allow_in_docker=settings.allow_cli_workers_in_docker,
        )
    if k == "cursor":
        return CursorWorker(
            settings.cursor_bin,
            "",
            enabled=settings.enable_cursor_worker,
            running_in_docker=settings.running_in_docker,
            allow_in_docker=settings.allow_cli_workers_in_docker,
        )
    raise ValueError(f"Unknown worker kind: {kind!r}")
