from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_orchestrator.db import models
from agent_orchestrator.settings import Settings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def branch_name_for_run(run_id: uuid.UUID) -> str:
    return f"ao/{run_id}"


def is_git_repo(repo: Path) -> bool:
    p = repo.resolve()
    return (p / ".git").exists()


def _has_git_metadata(path: Path) -> bool:
    return (path / ".git").exists()


def get_active_repo_worktree(session: Session, run_id: uuid.UUID) -> models.RepoWorktree | None:
    stmt = (
        select(models.RepoWorktree)
        .where(models.RepoWorktree.run_id == run_id, models.RepoWorktree.pruned_at.is_(None))
        .order_by(models.RepoWorktree.created_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def _git_rev_parse(worktree_path: Path) -> str | None:
    try:
        p = subprocess.run(
            ["git", "-C", str(worktree_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return p.stdout.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _run_git_worktree_add(base_repo: Path, worktree_path: Path, branch: str) -> None:
    base_repo = base_repo.resolve()
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["git", "-C", str(base_repo), "worktree", "add", "-b", branch, str(worktree_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if r.returncode == 0:
        return
    r2 = subprocess.run(
        ["git", "-C", str(base_repo), "worktree", "add", str(worktree_path), branch],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if r2.returncode != 0:
        msg = (r.stderr or r.stdout or r2.stderr or r2.stdout or "git worktree add failed").strip()
        raise RuntimeError(f"git worktree add failed: {msg[:500]}")


@dataclass(frozen=True)
class DispatchCwd:
    """cwd for WorkerInvocation and whether it is an isolated git worktree."""

    path: Path
    isolated: bool
    branch_name: str | None = None


class WorktreeManager:
    """Create and track per-run git worktrees under `.agent_worktrees/<run_id>`."""

    @staticmethod
    def worktree_directory(settings: Settings, run_id: uuid.UUID) -> Path:
        return settings.worktrees_dir.resolve() / str(run_id)

    @classmethod
    def ensure_dispatch_cwd(
        cls,
        session: Session,
        run: models.Run,
        settings: Settings,
    ) -> DispatchCwd:
        """
        If repo_path is a git repo, ensure a worktree at worktrees_dir/<run_id> on branch ao/<run_id>.
        If not a git repo, return base repo path (mock-only; real workers must not use this).
        """
        base = Path(run.repo_path).resolve()
        if not is_git_repo(base):
            return DispatchCwd(path=base, isolated=False, branch_name=None)

        existing = get_active_repo_worktree(session, run.id)
        if existing:
            wt = Path(existing.worktree_path)
            if wt.exists() and _has_git_metadata(wt):
                return DispatchCwd(
                    path=wt.resolve(), isolated=True, branch_name=existing.branch_name
                )
            existing.pruned_at = utc_now()
            session.flush()

        branch = branch_name_for_run(run.id)
        wt_path = cls.worktree_directory(settings, run.id)
        if wt_path.exists():
            raise RuntimeError(
                f"Worktree path {wt_path} already exists but is not registered as active; "
                "remove it or run `ao cleanup-worktree` for a stale run."
            )

        _run_git_worktree_add(base, wt_path, branch)
        commit_sha = _git_rev_parse(wt_path)

        session.add(
            models.RepoWorktree(
                id=uuid.uuid4(),
                run_id=run.id,
                base_repo_path=str(base),
                worktree_path=str(wt_path.resolve()),
                branch_name=branch,
                commit_sha=commit_sha,
                created_at=utc_now(),
                pruned_at=None,
            )
        )
        session.flush()
        return DispatchCwd(path=wt_path.resolve(), isolated=True, branch_name=branch)

    @classmethod
    def cleanup(
        cls,
        session: Session,
        run_id: uuid.UUID,
        settings: Settings,
    ) -> str:
        _ = settings  # reserved for future path policy
        row = get_active_repo_worktree(session, run_id)
        if not row:
            return "No active worktree record for this run."

        base = Path(row.base_repo_path).resolve()
        wt = Path(row.worktree_path).resolve()

        if wt.exists():
            r = subprocess.run(
                ["git", "-C", str(base), "worktree", "remove", str(wt), "--force"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if r.returncode != 0:
                err = (r.stderr or r.stdout or "").strip()
                return f"git worktree remove failed: {err[:300]}"

        row.pruned_at = utc_now()
        session.flush()
        return f"Removed worktree at {wt}"


def assert_real_worker_uses_isolated_worktree(repo_path: str, worktree_cwd: Path) -> None:
    """Real Claude/Codex/Cursor must never run with cwd equal to the original repo checkout."""
    base = Path(repo_path).resolve()
    cwd = worktree_cwd.resolve()
    if cwd == base:
        raise RuntimeError(
            "Refusing to dispatch real worker on the original repo path; an isolated git worktree is required."
        )
