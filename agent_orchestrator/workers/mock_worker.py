from __future__ import annotations

import time
from pathlib import Path

from agent_orchestrator.workers.base import WorkerInvocation, WorkerResult


class MockWorker:
    kind = "mock"

    def is_enabled(self) -> bool:
        return True

    def check_available(self) -> tuple[bool, str]:
        return True, "mock worker always available"

    def run(self, invocation: WorkerInvocation) -> WorkerResult:
        t0 = time.perf_counter()
        prompt = invocation.prompt_path.read_text(encoding="utf-8")
        out = invocation.prompt_path.parent / "worker_output.md"
        out.write_text(
            "## Mock worker output\n\n"
            f"(simulated execution for run `{invocation.run_id}`)\n\n"
            "### Prompt excerpt\n\n"
            f"{prompt[:2000]}\n",
            encoding="utf-8",
        )
        duration_ms = int((time.perf_counter() - t0) * 1000)
        return WorkerResult(exit_code=0, stdout_path=out, stderr_path=None, duration_ms=duration_ms)
