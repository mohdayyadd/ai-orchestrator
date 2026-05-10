from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_orchestrator.db import models
from agent_orchestrator.settings import Settings
from agent_orchestrator.services.worktree_manager import (
    WorktreeManager,
    assert_real_worker_uses_isolated_worktree,
)
from agent_orchestrator.workers.base import WorkerInvocation
from agent_orchestrator.workers.registry import get_worker


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def run_dir_for(settings: Settings, run_id: uuid.UUID) -> Path:
    root = settings.artifacts_dir
    root.mkdir(parents=True, exist_ok=True)
    return root / str(run_id)


def write_artifact_record(
    session: Session,
    run_id: uuid.UUID,
    kind: str,
    relative_path: str,
) -> None:
    session.add(
        models.Artifact(
            id=uuid.uuid4(),
            run_id=run_id,
            kind=kind,
            relative_path=relative_path,
            sha256=None,
            created_at=utc_now(),
        )
    )


def get_or_create_project(session: Session, repo_path: Path, settings: Settings) -> models.Project:
    slug = repo_path.resolve().name.replace(" ", "-").lower()[:200]
    row = session.execute(select(models.Project).where(models.Project.slug == slug)).scalar_one_or_none()
    if row:
        return row
    p = models.Project(
        id=uuid.uuid4(),
        name=slug,
        slug=slug,
        default_repo_path=str(repo_path.resolve()),
        settings_json={},
        created_at=utc_now(),
    )
    session.add(p)
    session.flush()
    return p


def create_run_record(
    session: Session,
    *,
    task_file: Path,
    repo_path: Path,
    settings: Settings,
) -> models.Run:
    task_file = task_file.resolve()
    repo_path = repo_path.resolve()
    if not task_file.is_file():
        raise FileNotFoundError(f"Task file not found: {task_file}")
    if not repo_path.exists():
        raise FileNotFoundError(f"Repo path not found: {repo_path}")

    project = get_or_create_project(session, repo_path, settings)
    run_id = uuid.uuid4()
    rdir = run_dir_for(settings, run_id)
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "agent_outputs").mkdir(exist_ok=True)
    (rdir / "reviews").mkdir(exist_ok=True)

    shutil.copy2(task_file, rdir / "task.md")
    (rdir / "subtasks.json").write_text("[]\n", encoding="utf-8")

    # Placeholder artifact manifests (populated by phases)
    for name, content in [
        ("ecc_recommendations.json", "{}\n"),
        ("ecc_components_used.json", "[]\n"),
        ("obsidian_notes.json", "[]\n"),
        ("ecc_security_scan.md", "# ECC security scan\n\n(not run)\n"),
        ("obsidian_sync.md", "# Obsidian sync\n\n(disabled or not synced)\n"),
    ]:
        (rdir / name).write_text(content, encoding="utf-8")

    run = models.Run(
        id=run_id,
        project_id=project.id,
        status="created",
        phase="created",
        task_path=str(task_file),
        repo_path=str(repo_path),
        max_iterations=5,
        iteration_count=0,
        selected_worker=None,
        artifact_root=str(rdir.resolve()),
        metadata_json={},
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add(run)
    session.flush()

    write_artifact_record(session, run_id, "task", "task.md")
    session.add(
        models.RunStep(
            id=uuid.uuid4(),
            run_id=run_id,
            step_type="create_run",
            status="completed",
            payload_json={"task_path": str(task_file), "repo_path": str(repo_path)},
            error=None,
            started_at=utc_now(),
            finished_at=utc_now(),
        )
    )
    return run


def _git_capture(repo: Path, *args: str) -> str:
    try:
        p = subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if p.returncode != 0:
            return f"(git {' '.join(args)} failed: {p.stderr.strip()[:500]})"
        return p.stdout.strip() or "(empty)"
    except FileNotFoundError:
        return "(git not installed)"
    except subprocess.TimeoutExpired:
        return "(git command timeout)"


def _is_git_repo(path: Path) -> bool:
    return (path / ".git").exists()


def _read_if_exists(path: Path, label: str) -> str:
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8", errors="replace")[:50_000]
        except OSError as e:
            return f"({label}: could not read: {e})"
    return f"({label}: not found)"


def _limited_tree(repo: Path, max_files: int = 80) -> str:
    lines: list[str] = []
    count = 0
    for p in sorted(repo.rglob("*")):
        if p.is_dir():
            continue
        if any(part in {".git", "__pycache__", ".venv", "node_modules"} for part in p.parts):
            continue
        rel = p.relative_to(repo)
        lines.append(str(rel).replace("\\", "/"))
        count += 1
        if count >= max_files:
            lines.append("... (truncated)")
            break
    return "\n".join(lines) if lines else "(no files listed)"


def build_context_pack(repo_path: Path, run_dir: Path) -> str:
    repo = repo_path.resolve()
    parts: list[str] = []
    parts.append("# Context pack\n")
    parts.append("## Repository tree (limited)\n")
    parts.append("```\n" + _limited_tree(repo) + "\n```\n")

    if _is_git_repo(repo):
        parts.append("## git status\n```\n" + _git_capture(repo, "status", "--short", "--branch") + "\n```\n")
        parts.append("## git diff (stat)\n```\n" + _git_capture(repo, "diff", "--stat", "HEAD") + "\n```\n")
    else:
        parts.append("## git\n(not a git repository)\n")

    for fname in ("README.md", "CLAUDE.md", "AGENTS.md", "pyproject.toml", "package.json"):
        parts.append(f"## {fname}\n")
        parts.append(_read_if_exists(repo / fname, fname) + "\n")

    task = run_dir / "task.md"
    parts.append("## Task\n")
    parts.append(_read_if_exists(task, "task.md") + "\n")

    return "\n".join(parts)


def analyze_clarification(task_text: str) -> tuple[bool, list[str]]:
    """Return (blocking, questions)."""
    lines = [ln.strip() for ln in task_text.splitlines() if ln.strip()]
    text = task_text.lower()
    questions: list[str] = []
    if "needs_clarification" in text or "needs clarification" in text:
        questions.append("The task marks NEEDS_CLARIFICATION — what exact outcome and constraints should apply?")
    if len(task_text.strip()) < 40:
        questions.append("The task is very short — what is the acceptance criteria and scope boundary?")
    if "???" in task_text:
        questions.append("Unresolved '???' placeholders found — please replace with concrete requirements.")
    blocking = bool(questions)
    return blocking, questions


def plan_run(session: Session, run: models.Run, settings: Settings) -> tuple[bool, str]:
    """Returns (ok, message). If clarification blocks, ok False."""
    run_dir = Path(run.artifact_root)
    task_text = (run_dir / "task.md").read_text(encoding="utf-8", errors="replace")
    blocking, qs = analyze_clarification(task_text)

    step = models.RunStep(
        id=uuid.uuid4(),
        run_id=run.id,
        step_type="plan",
        status="running",
        payload_json={},
        error=None,
        started_at=utc_now(),
        finished_at=None,
    )
    session.add(step)
    session.flush()

    cp = build_context_pack(Path(run.repo_path), run_dir)
    (run_dir / "context_pack.md").write_text(cp, encoding="utf-8")
    write_artifact_record(session, run.id, "context_pack", "context_pack.md")

    clar_path = run_dir / "clarification.md"
    if blocking:
        clar_path.write_text(
            "# Clarification required\n\n" + "\n".join(f"- {q}" for q in qs) + "\n",
            encoding="utf-8",
        )
        write_artifact_record(session, run.id, "clarification", "clarification.md")
        run.status = "waiting_clarification"
        run.phase = "clarification"
        run.updated_at = utc_now()
        step.status = "blocked"
        step.finished_at = utc_now()
        step.payload_json = {"blocking": True, "questions": qs}
        session.flush()
        return False, "Blocking clarification questions were written to clarification.md"

    clar_path.write_text("# Clarification\n\nNo blocking questions.\n", encoding="utf-8")
    write_artifact_record(session, run.id, "clarification", "clarification.md")

    plan_body = (
        "# Plan\n\n"
        "## Summary\n"
        "Execute the task in the provided repository using the selected worker after dispatch.\n\n"
        "## Steps\n"
        "1. Review context pack and repository state.\n"
        "2. Implement changes in an isolated worktree (when git is available).\n"
        "3. Run safe tests if configured.\n"
        "4. Produce handoff documentation.\n"
    )
    (run_dir / "plan.md").write_text(plan_body, encoding="utf-8")
    write_artifact_record(session, run.id, "plan", "plan.md")

    routing = {
        "rules_version": "v1-rules",
        "default_worker": "mock",
        "notes": "Container-friendly default is mock; host-runner enables subscription CLIs.",
    }
    (run_dir / "routing.json").write_text(json.dumps(routing, indent=2) + "\n", encoding="utf-8")
    write_artifact_record(session, run.id, "routing", "routing.json")

    session.add(
        models.ModelRoutingDecision(
            id=uuid.uuid4(),
            run_id=run.id,
            rules_version="v1-rules",
            inputs_json={"repo": run.repo_path},
            chosen_worker="mock",
            chosen_tier="local",
            rationale_text="Default V1 routing prefers mock in Docker; override at dispatch.",
            llm_rationale=None,
            created_at=utc_now(),
        )
    )

    run.status = "planned"
    run.phase = "planned"
    run.updated_at = utc_now()
    step.status = "completed"
    step.finished_at = utc_now()
    step.payload_json = {"blocking": False}
    session.flush()
    return True, "Plan and context pack written"


def dispatch_run(
    session: Session,
    run: models.Run,
    agent: str,
    *,
    settings: Settings,
    yes: bool,
    timeout_seconds: int = 3600,
) -> None:
    worker = get_worker(agent, settings)
    if agent != "mock" and not worker.is_enabled():
        raise RuntimeError(f"Worker {agent!r} is not enabled in settings")

    if agent != "mock":
        if not (yes or settings.allow_skip_confirmations):
            raise RuntimeError(
                "Real agent dispatch requires confirmation. Re-run with --yes or set ALLOW_SKIP_CONFIRMATIONS=true (dev only)."
            )
        ok, msg = worker.check_available()
        if not ok:
            raise RuntimeError(msg)

    run_dir = Path(run.artifact_root)
    repo = Path(run.repo_path)

    dispatch_cwd = WorktreeManager.ensure_dispatch_cwd(session, run, settings)

    if agent != "mock":
        if not dispatch_cwd.isolated:
            raise RuntimeError(
                "Real workers (claude/codex/cursor) require a git repository at repo_path "
                "so an isolated worktree can be created under WORKTREES_DIR."
            )
        assert_real_worker_uses_isolated_worktree(run.repo_path, dispatch_cwd.path)

    worktree_path = dispatch_cwd.path

    prompt = (
        (run_dir / "plan.md").read_text(encoding="utf-8", errors="replace")
        if (run_dir / "plan.md").is_file()
        else "# Plan\n(none yet)\n"
    )
    ctx = (run_dir / "context_pack.md").read_text(encoding="utf-8", errors="replace")
    wp = run_dir / "worker_prompt.md"
    wp.write_text(
        "# Worker prompt\n\n## Context pack\n\n"
        + ctx[:120_000]
        + "\n\n## Plan\n\n"
        + prompt[:40_000],
        encoding="utf-8",
    )
    write_artifact_record(session, run.id, "worker_prompt", "worker_prompt.md")

    inv = WorkerInvocation(
        run_id=str(run.id),
        worktree_path=worktree_path,
        prompt_path=wp,
        timeout_seconds=timeout_seconds,
        metadata={"agent": agent},
    )

    t_start = utc_now()
    result = worker.run(inv)
    t_end = utc_now()

    out_path = run_dir / "worker_output.md"
    if result.stdout_path and Path(result.stdout_path).is_file():
        src_p = Path(result.stdout_path).resolve()
        dst_p = out_path.resolve()
        if src_p != dst_p:
            shutil.copy2(result.stdout_path, out_path)
    if not out_path.is_file():
        out_path.write_text("(no stdout captured)\n", encoding="utf-8")
    write_artifact_record(session, run.id, "worker_output", "worker_output.md")

    session.add(
        models.AgentInvocation(
            id=uuid.uuid4(),
            run_id=run.id,
            worker_kind=agent,
            command_argv_json=[agent, "subprocess"],
            exit_code=result.exit_code,
            stdout_path=str(result.stdout_path) if result.stdout_path else None,
            stderr_path=str(result.stderr_path) if result.stderr_path else None,
            duration_ms=result.duration_ms,
            created_at=t_end,
        )
    )

    # test_results stub
    (run_dir / "test_results.md").write_text(
        "# Test results\n\n(no safe test commands executed in V1 default)\n", encoding="utf-8"
    )
    write_artifact_record(session, run.id, "test_results", "test_results.md")

    run.selected_worker = agent
    run.status = "dispatched" if result.exit_code == 0 else "dispatch_failed"
    run.phase = "dispatched"
    run.updated_at = utc_now()
    session.add(
        models.RunStep(
            id=uuid.uuid4(),
            run_id=run.id,
            step_type="dispatch",
            status="completed" if result.exit_code == 0 else "failed",
            payload_json={
                "agent": agent,
                "exit_code": result.exit_code,
                "repo_path": str(repo.resolve()),
                "worktree_path": str(worktree_path.resolve()),
                "worktree_branch": dispatch_cwd.branch_name,
            },
            error=None if result.exit_code == 0 else f"exit {result.exit_code}",
            started_at=t_start,
            finished_at=t_end,
        )
    )
    session.flush()


def review_run(session: Session, run: models.Run) -> None:
    run_dir = Path(run.artifact_root)
    wo = _read_if_exists(run_dir / "worker_output.md", "worker_output.md")
    plan = _read_if_exists(run_dir / "plan.md", "plan.md")
    review = (
        "# Review\n\n"
        "## Plan excerpt\n\n"
        + plan[:4000]
        + "\n\n## Worker output excerpt\n\n"
        + wo[:8000]
        + "\n"
    )
    (run_dir / "review.md").write_text(review, encoding="utf-8")
    write_artifact_record(session, run.id, "review", "review.md")

    handoff = (
        "# Final handoff\n\n"
        f"- run_id: `{run.id}`\n"
        f"- worker: `{run.selected_worker}`\n"
        f"- status: `{run.status}`\n"
        f"- artifacts: `{run.artifact_root}`\n\n"
        "## Summary\n"
        "See review.md and worker_output.md for details.\n"
    )
    (run_dir / "final_handoff.md").write_text(handoff, encoding="utf-8")
    write_artifact_record(session, run.id, "final_handoff", "final_handoff.md")

    trace = (
        "# Orchestration trace\n\n"
        "V1 synchronous trace; persisted rows in Postgres: run_steps, agent_invocations, artifacts.\n"
    )
    (run_dir / "orchestration_trace.md").write_text(trace, encoding="utf-8")
    write_artifact_record(session, run.id, "orchestration_trace", "orchestration_trace.md")

    run.status = "reviewed"
    run.phase = "reviewed"
    run.updated_at = utc_now()
    session.add(
        models.RunStep(
            id=uuid.uuid4(),
            run_id=run.id,
            step_type="review",
            status="completed",
            payload_json={},
            error=None,
            started_at=utc_now(),
            finished_at=utc_now(),
        )
    )
    session.flush()


def load_run(session: Session, run_id: uuid.UUID) -> models.Run | None:
    return session.execute(select(models.Run).where(models.Run.id == run_id)).scalar_one_or_none()
