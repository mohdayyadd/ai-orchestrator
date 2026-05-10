from __future__ import annotations

import shlex
import shutil
import subprocess
import time
from pathlib import Path

from agent_orchestrator.workers.base import WorkerInvocation, WorkerResult


def _run_version(binary: str) -> tuple[bool, str]:
    try:
        p = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if p.returncode == 0:
            msg = (p.stdout or p.stderr or "").strip().splitlines()[0][:200]
            return True, msg or "ok"
        return False, (p.stderr or p.stdout or "non-zero exit")[:200]
    except FileNotFoundError:
        return False, "binary not found on PATH"
    except subprocess.TimeoutExpired:
        return False, "timeout"


class ClaudeCodeWorker:
    kind = "claude"

    def __init__(
        self,
        binary: str,
        extra_args: str,
        *,
        enabled: bool,
        running_in_docker: bool,
        allow_in_docker: bool,
    ) -> None:
        self._binary = binary
        self._extra_args = extra_args
        self._enabled = enabled
        self._running_in_docker = running_in_docker
        self._allow_in_docker = allow_in_docker

    def is_enabled(self) -> bool:
        return self._enabled

    def check_available(self) -> tuple[bool, str]:
        if not self._enabled:
            return False, "Claude worker disabled (ENABLE_CLAUDE_WORKER=false)"
        if self._running_in_docker and not self._allow_in_docker:
            return (
                False,
                "Host-runner only: real Claude CLI is disabled inside Docker by default. "
                "Run `uv run ao dispatch ...` on the host or set ALLOW_CLI_WORKERS_IN_DOCKER=true (discouraged).",
            )
        return _run_version(self._binary)

    def run(self, invocation: WorkerInvocation) -> WorkerResult:
        ok, msg = self.check_available()
        if not ok:
            raise RuntimeError(msg)
        stdout_path = invocation.worktree_path.parent / "agent_outputs" / "claude_stdout.log"
        stderr_path = invocation.worktree_path.parent / "agent_outputs" / "claude_stderr.log"
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()
        extra = shlex.split(self._extra_args) if self._extra_args.strip() else []
        cmd = [self._binary, *extra]
        with (
            open(invocation.prompt_path, encoding="utf-8") as prompt_f,
            open(stdout_path, "w", encoding="utf-8") as out_f,
            open(stderr_path, "w", encoding="utf-8") as err_f,
        ):
            proc = subprocess.run(
                cmd,
                cwd=str(invocation.worktree_path),
                stdin=prompt_f,
                stdout=out_f,
                stderr=err_f,
                timeout=invocation.timeout_seconds,
                text=True,
            )
        duration_ms = int((time.perf_counter() - t0) * 1000)
        return WorkerResult(
            exit_code=proc.returncode,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            duration_ms=duration_ms,
        )


class CodexWorker:
    kind = "codex"

    def __init__(
        self,
        binary: str,
        extra_args: str,
        *,
        enabled: bool,
        running_in_docker: bool,
        allow_in_docker: bool,
    ) -> None:
        self._binary = binary
        self._extra_args = extra_args
        self._enabled = enabled
        self._running_in_docker = running_in_docker
        self._allow_in_docker = allow_in_docker

    def is_enabled(self) -> bool:
        return self._enabled

    def check_available(self) -> tuple[bool, str]:
        if not self._enabled:
            return False, "Codex worker disabled (ENABLE_CODEX_WORKER=false)"
        if self._running_in_docker and not self._allow_in_docker:
            return (
                False,
                "Host-runner only: real Codex CLI is disabled inside Docker by default. "
                "Run `uv run ao dispatch ...` on the host or set ALLOW_CLI_WORKERS_IN_DOCKER=true (discouraged).",
            )
        return _run_version(self._binary)

    def run(self, invocation: WorkerInvocation) -> WorkerResult:
        ok, msg = self.check_available()
        if not ok:
            raise RuntimeError(msg)
        stdout_path = invocation.worktree_path.parent / "agent_outputs" / "codex_stdout.log"
        stderr_path = invocation.worktree_path.parent / "agent_outputs" / "codex_stderr.log"
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()
        extra = shlex.split(self._extra_args) if self._extra_args.strip() else []
        cmd = [self._binary, *extra]
        with (
            open(invocation.prompt_path, encoding="utf-8") as prompt_f,
            open(stdout_path, "w", encoding="utf-8") as out_f,
            open(stderr_path, "w", encoding="utf-8") as err_f,
        ):
            proc = subprocess.run(
                cmd,
                cwd=str(invocation.worktree_path),
                stdin=prompt_f,
                stdout=out_f,
                stderr=err_f,
                timeout=invocation.timeout_seconds,
                text=True,
            )
        duration_ms = int((time.perf_counter() - t0) * 1000)
        return WorkerResult(
            exit_code=proc.returncode,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            duration_ms=duration_ms,
        )


class CursorWorker:
    kind = "cursor"

    def __init__(
        self,
        binary: str,
        extra_args: str,
        *,
        enabled: bool,
        running_in_docker: bool,
        allow_in_docker: bool,
    ) -> None:
        self._binary = binary
        self._extra_args = extra_args
        self._enabled = enabled
        self._running_in_docker = running_in_docker
        self._allow_in_docker = allow_in_docker

    def is_enabled(self) -> bool:
        return self._enabled

    def check_available(self) -> tuple[bool, str]:
        if not self._enabled:
            return False, "Cursor worker disabled (ENABLE_CURSOR_WORKER=false)"
        if self._running_in_docker and not self._allow_in_docker:
            return False, "Host-runner only for Cursor CLI (or ALLOW_CLI_WORKERS_IN_DOCKER=true)."
        if not shutil.which(self._binary):
            return False, "cursor binary not found on PATH"
        return True, "configured (placeholder)"

    def run(self, invocation: WorkerInvocation) -> WorkerResult:
        ok, msg = self.check_available()
        if not ok:
            raise RuntimeError(msg)
        raise NotImplementedError(
            "CursorWorker is a placeholder; enable and extend when a stable headless CLI contract exists."
        )
