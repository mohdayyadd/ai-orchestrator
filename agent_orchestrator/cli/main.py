from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import redis
import typer
from rich.console import Console
from rich.table import Table

from agent_orchestrator.db.session import session_scope
from agent_orchestrator.services import run_ops
from agent_orchestrator.services.worktree_manager import WorktreeManager, get_active_repo_worktree
from agent_orchestrator.settings import get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


def main() -> None:
    app()


@app.command()
def init() -> None:
    """Create local directories and config scaffolding (no DB required)."""
    s = get_settings()
    s.artifacts_dir.mkdir(parents=True, exist_ok=True)
    s.worktrees_dir.mkdir(parents=True, exist_ok=True)
    s.tasks_dir.mkdir(parents=True, exist_ok=True)
    Path("workspace/repos").mkdir(parents=True, exist_ok=True)
    Path("workspace/ecc").mkdir(parents=True, exist_ok=True)
    Path("workspace/obsidian-vault").mkdir(parents=True, exist_ok=True)
    Path(".agent_orchestrator").mkdir(parents=True, exist_ok=True)
    console.print("[green]ok[/green]: local workspace directories ensured")


def _check_cmd(argv: list[str], timeout: float = 15.0) -> tuple[bool, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        line = (p.stdout or p.stderr or "").strip().splitlines()[:1]
        hint = line[0][:200] if line else ("ok" if p.returncode == 0 else "no output")
        return p.returncode == 0, hint
    except FileNotFoundError:
        return False, "not found"
    except subprocess.TimeoutExpired:
        return False, "timeout"


@app.command()
def doctor() -> None:
    """Validate environment: Postgres, Redis, paths, git, optional workers."""
    s = get_settings()
    table = Table(title="ao doctor")
    table.add_column("check")
    table.add_column("status")
    table.add_column("detail")

    # Postgres
    try:
        from sqlalchemy import text

        from agent_orchestrator.db.session import get_engine

        eng = get_engine()
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        table.add_row("postgres", "ok", "connected")
    except Exception as e:
        table.add_row("postgres", "fail", str(e)[:200])

    # Redis
    try:
        r = redis.Redis.from_url(s.redis_url, socket_connect_timeout=2)
        r.ping()
        table.add_row("redis", "ok", "PING")
    except Exception as e:
        table.add_row("redis", "fail", str(e)[:200])

    table.add_row(
        "artifacts_dir",
        "ok" if s.artifacts_dir.exists() else "warn",
        str(s.artifacts_dir),
    )
    table.add_row(
        "worktrees_dir",
        "ok" if s.worktrees_dir.exists() else "warn",
        str(s.worktrees_dir),
    )
    table.add_row("workspace_root", "ok", str(s.workspace_root))
    ok_git, hint_git = _check_cmd(["git", "--version"])
    table.add_row("git", "ok" if ok_git else "fail", hint_git)

    if s.enable_claude_worker:
        ok, hint = _check_cmd([s.claude_code_bin, "--version"])
        table.add_row("claude_cli", "ok" if ok else "fail", hint)
    else:
        table.add_row("claude_cli", "skipped", "ENABLE_CLAUDE_WORKER=false")

    if s.enable_codex_worker:
        ok, hint = _check_cmd([s.codex_bin, "--version"])
        table.add_row("codex_cli", "ok" if ok else "fail", hint)
    else:
        table.add_row("codex_cli", "skipped", "ENABLE_CODEX_WORKER=false")

    if s.enable_cursor_worker:
        ok, hint = _check_cmd([s.cursor_bin, "--version"])
        table.add_row("cursor_cli", "ok" if ok else "warn", hint)
    else:
        table.add_row("cursor_cli", "skipped", "ENABLE_CURSOR_WORKER=false")

    console.print(table)


@app.command("create-run")
def create_run(task: Path = typer.Option(..., "--task"), repo: Path = typer.Option(..., "--repo")) -> None:
    s = get_settings()
    with session_scope() as session:
        run = run_ops.create_run_record(session, task_file=task, repo_path=repo, settings=s)
        console.print(f"[green]created run[/green] {run.id}")
        console.print(f"artifacts: {run.artifact_root}")


@app.command()
def plan(run_id: str) -> None:
    s = get_settings()
    rid = uuid.UUID(run_id)
    with session_scope() as session:
        run = run_ops.load_run(session, rid)
        if not run:
            raise typer.BadParameter("run not found")
        ok, msg = run_ops.plan_run(session, run, s)
        if not ok:
            console.print(f"[yellow]{msg}[/yellow]")
            raise typer.Exit(code=2)
        console.print(f"[green]planned[/green] {run_id}: {msg}")


@app.command()
def dispatch(
    run_id: str,
    agent: str = typer.Option("mock", "--agent"),
    yes: bool = typer.Option(False, "--yes", "-y"),
    timeout: int = typer.Option(3600, "--timeout"),
) -> None:
    s = get_settings()
    rid = uuid.UUID(run_id)
    with session_scope() as session:
        run = run_ops.load_run(session, rid)
        if not run:
            raise typer.BadParameter("run not found")
        run_ops.dispatch_run(session, run, agent, settings=s, yes=yes, timeout_seconds=timeout)
        console.print(f"[green]dispatched[/green] {run_id} with agent={agent}")


@app.command()
def review(run_id: str) -> None:
    rid = uuid.UUID(run_id)
    with session_scope() as session:
        run = run_ops.load_run(session, rid)
        if not run:
            raise typer.BadParameter("run not found")
        run_ops.review_run(session, run)
        console.print(f"[green]reviewed[/green] {run_id}")


@app.command()
def status(run_id: str) -> None:
    rid = uuid.UUID(run_id)
    with session_scope() as session:
        run = run_ops.load_run(session, rid)
        if not run:
            raise typer.BadParameter("run not found")
        wt = get_active_repo_worktree(session, rid)
        wt_line = (
            f"  worktree: {wt.worktree_path}\n  branch:   {wt.branch_name}\n"
            if wt
            else "  worktree: (none active)\n  branch:   -\n"
        )
        console.print(
            f"run {run.id}\n"
            f"  status: {run.status}\n"
            f"  phase: {run.phase}\n"
            f"  worker: {run.selected_worker}\n"
            f"  artifacts: {run.artifact_root}\n"
            f"  repo (original): {run.repo_path}\n"
            + wt_line
        )


@app.command("cleanup-worktree")
def cleanup_worktree(run_id: str) -> None:
    """Remove the git worktree for a run (git worktree remove --force) and mark DB row pruned."""
    rid = uuid.UUID(run_id)
    s = get_settings()
    with session_scope() as session:
        msg = WorktreeManager.cleanup(session, rid, s)
        console.print(msg)


@app.command("list-runs")
def list_runs(limit: int = typer.Option(20, "--limit")) -> None:
    from sqlalchemy import select

    from agent_orchestrator.db import models

    with session_scope() as session:
        rows = session.execute(select(models.Run).order_by(models.Run.created_at.desc()).limit(limit)).scalars().all()
        for r in rows:
            console.print(f"{r.id}  {r.status:16}  {r.phase:16}  {r.created_at}")


@app.command()
def solve(
    task: Path = typer.Option(..., "--task"),
    repo: Path = typer.Option(..., "--repo"),
    auto: bool = typer.Option(True, "--auto/--no-auto"),
    agent: str = typer.Option("mock", "--agent"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Run create-run → plan → dispatch → review (stops if clarification blocks)."""
    s = get_settings()
    with session_scope() as session:
        run = run_ops.create_run_record(session, task_file=task, repo_path=repo, settings=s)
        rid = run.id
    console.print(f"created {rid}")
    with session_scope() as session:
        run = run_ops.load_run(session, rid)
        assert run
        ok, msg = run_ops.plan_run(session, run, s)
        if not ok:
            console.print(f"[yellow]plan blocked:[/yellow] {msg}")
            raise typer.Exit(code=2)
    with session_scope() as session:
        run = run_ops.load_run(session, rid)
        assert run
        run_ops.dispatch_run(session, run, agent, settings=s, yes=yes, timeout_seconds=3600)
    with session_scope() as session:
        run = run_ops.load_run(session, rid)
        assert run
        run_ops.review_run(session, run)
    console.print(f"[green]solve complete[/green] {rid}")


ecc_app = typer.Typer(no_args_is_help=True, help="Everything Claude Code (optional)")
app.add_typer(ecc_app, name="ecc")


@ecc_app.command("status")
def ecc_status() -> None:
    from agent_orchestrator.ecc.service import ecc_status as _st

    console.print(_st())


@ecc_app.command("sync")
def ecc_sync() -> None:
    from agent_orchestrator.ecc.service import ecc_sync as _sync

    console.print(_sync())


@ecc_app.command("list-components")
def ecc_list_components() -> None:
    from agent_orchestrator.ecc.service import ecc_list_components as _lc

    for line in _lc():
        console.print(line)


@ecc_app.command("inspect")
def ecc_inspect(component: str) -> None:
    from agent_orchestrator.ecc.service import ecc_inspect as _insp

    console.print(_insp(component))


@ecc_app.command("recommend")
def ecc_recommend(run_id: str) -> None:
    from agent_orchestrator.ecc.service import ecc_recommend as _rec

    console.print(_rec(uuid.UUID(run_id)))


@ecc_app.command("apply")
def ecc_apply(
    run_id: str,
    component: str = typer.Option(..., "--component"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    from agent_orchestrator.ecc.service import ecc_apply as _apply

    console.print(_apply(uuid.UUID(run_id), component, yes=yes))


@ecc_app.command("install")
def ecc_install(
    target: str = typer.Option(..., "--target"),
    profile: str = typer.Option("minimal", "--profile"),
    dry_run: bool = typer.Option(True, "--dry-run/--execute"),
) -> None:
    from agent_orchestrator.ecc.service import ecc_install as _inst

    console.print(_inst(target, profile, dry_run=dry_run))


@ecc_app.command("security-scan")
def ecc_security_scan() -> None:
    from agent_orchestrator.ecc.service import ecc_security_scan as _scan

    console.print(_scan())


obs_app = typer.Typer(no_args_is_help=True, help="Obsidian vault writer (optional)")
app.add_typer(obs_app, name="obsidian")


@obs_app.command("status")
def obsidian_status() -> None:
    from agent_orchestrator.obsidian.service import obsidian_status as _st

    console.print(_st())


@obs_app.command("init-vault")
def obsidian_init_vault() -> None:
    from agent_orchestrator.obsidian.service import obsidian_init_vault as _iv

    console.print(_iv())


@obs_app.command("write-run-summary")
def obsidian_write_run_summary(run_id: str) -> None:
    from agent_orchestrator.obsidian.service import write_run_summary as _w

    console.print(_w(uuid.UUID(run_id)))


@obs_app.command("write-decision")
def obsidian_write_decision(run_id: str) -> None:
    from agent_orchestrator.obsidian.service import write_decision as _w

    console.print(_w(uuid.UUID(run_id)))


@obs_app.command("write-learning")
def obsidian_write_learning(run_id: str) -> None:
    from agent_orchestrator.obsidian.service import write_learning as _w

    console.print(_w(uuid.UUID(run_id)))


@obs_app.command("sync-run")
def obsidian_sync_run(run_id: str) -> None:
    from agent_orchestrator.obsidian.service import sync_run as _s

    console.print(_s(uuid.UUID(run_id)))


@obs_app.command("search")
def obsidian_search(query: str) -> None:
    from agent_orchestrator.obsidian.service import search_notes as _s

    for line in _s(query):
        console.print(line)


@obs_app.command("open-run")
def obsidian_open_run(run_id: str) -> None:
    from agent_orchestrator.obsidian.service import open_run as _o

    console.print(_o(uuid.UUID(run_id)))


worker_app = typer.Typer(no_args_is_help=True, help="Background worker (Redis stub in V1)")
app.add_typer(worker_app, name="worker")


@worker_app.command("run")
def worker_run() -> None:
    from agent_orchestrator.jobs.redis_worker import run_worker_loop

    run_worker_loop()


if __name__ == "__main__":
    main()
