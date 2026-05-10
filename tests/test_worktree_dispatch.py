"""Git worktree isolation for dispatch."""

from __future__ import annotations

import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_orchestrator.db import models
from agent_orchestrator.services.run_ops import dispatch_run
from agent_orchestrator.services.worktree_manager import (
    DispatchCwd,
    WorktreeManager,
    assert_real_worker_uses_isolated_worktree,
    branch_name_for_run,
    is_git_repo,
)
from agent_orchestrator.settings import Settings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _git_init_commit(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    (repo / "file.txt").write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "myrepo"
    _git_init_commit(repo)
    return repo


def test_branch_name_uses_ao_prefix() -> None:
    rid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert branch_name_for_run(rid) == f"ao/{rid}"


def test_assert_real_worker_rejects_base_repo_path() -> None:
    base = Path("/tmp/base/repo").resolve()
    with pytest.raises(RuntimeError, match="original repo path"):
        assert_real_worker_uses_isolated_worktree(str(base), base)


def test_is_git_repo_false_without_dot_git(tmp_path: Path) -> None:
    d = tmp_path / "nogit"
    d.mkdir()
    assert not is_git_repo(d)


@pytest.mark.skipif(not shutil.which("git"), reason="git not installed")
def test_worktree_manager_creates_isolated_path(tmp_git_repo: Path, tmp_path: Path) -> None:
    run_id = uuid.uuid4()
    worktrees_root = tmp_path / "agent_worktrees"
    settings = MagicMock(spec=Settings)
    settings.worktrees_dir = worktrees_root

    proj = models.Project(
        id=uuid.uuid4(),
        name="p",
        slug="p-slug",
        default_repo_path=str(tmp_git_repo),
        settings_json={},
        created_at=utc_now(),
    )
    run = models.Run(
        id=run_id,
        project_id=proj.id,
        status="planned",
        phase="planned",
        task_path=str(tmp_path / "task.md"),
        repo_path=str(tmp_git_repo.resolve()),
        max_iterations=5,
        iteration_count=0,
        selected_worker=None,
        artifact_root=str(tmp_path / "artifacts" / str(run_id)),
        metadata_json={},
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None

    dc = WorktreeManager.ensure_dispatch_cwd(session, run, settings)
    assert dc.isolated
    assert dc.branch_name == branch_name_for_run(run_id)
    assert dc.path.resolve() == (worktrees_root.resolve() / str(run_id))
    assert dc.path.resolve() != tmp_git_repo.resolve()
    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert isinstance(added, models.RepoWorktree)
    assert added.branch_name == branch_name_for_run(run_id)


class _CaptureMockWorker:
    kind = "mock"

    def __init__(self) -> None:
        self.invocations: list = []

    def is_enabled(self) -> bool:
        return True

    def check_available(self) -> tuple[bool, str]:
        return True, "ok"

    def run(self, invocation):
        from agent_orchestrator.workers.base import WorkerResult

        self.invocations.append(invocation)
        out = invocation.prompt_path.parent / "worker_output.md"
        out.write_text("ok\n", encoding="utf-8")
        return WorkerResult(exit_code=0, stdout_path=out, stderr_path=None, duration_ms=1)


@pytest.mark.skipif(not shutil.which("git"), reason="git not installed")
def test_dispatch_mock_uses_worktree_path_not_base_repo(
    tmp_git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = uuid.uuid4()
    isolated_wt = tmp_path / "wt" / str(run_id)
    isolated_wt.mkdir(parents=True)

    art = tmp_path / "artifacts" / str(run_id)
    art.mkdir(parents=True)
    (art / "plan.md").write_text("# p\n", encoding="utf-8")
    (art / "context_pack.md").write_text("# c\n", encoding="utf-8")

    proj = models.Project(
        id=uuid.uuid4(),
        name="p",
        slug="p2",
        default_repo_path=str(tmp_git_repo),
        settings_json={},
        created_at=utc_now(),
    )
    run = models.Run(
        id=run_id,
        project_id=proj.id,
        status="planned",
        phase="planned",
        task_path=str(tmp_path / "t.md"),
        repo_path=str(tmp_git_repo.resolve()),
        max_iterations=5,
        iteration_count=0,
        selected_worker=None,
        artifact_root=str(art),
        metadata_json={},
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    settings = MagicMock(spec=Settings)
    settings.allow_skip_confirmations = False

    def fake_ensure(session, r, s):
        _ = (session, s)
        assert r.id == run_id
        return DispatchCwd(
            path=isolated_wt.resolve(), isolated=True, branch_name=branch_name_for_run(run_id)
        )

    # DispatchCwd is module-level dataclass; patch ensure_dispatch_cwd
    monkeypatch.setattr(
        "agent_orchestrator.services.run_ops.WorktreeManager.ensure_dispatch_cwd",
        fake_ensure,
    )

    cap = _CaptureMockWorker()
    monkeypatch.setattr("agent_orchestrator.services.run_ops.get_worker", lambda _a, _s: cap)

    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None

    dispatch_run(session, run, "mock", settings=settings, yes=False)

    assert len(cap.invocations) == 1
    assert cap.invocations[0].worktree_path.resolve() == isolated_wt.resolve()
    assert cap.invocations[0].worktree_path.resolve() != tmp_git_repo.resolve()


@pytest.mark.skipif(not shutil.which("git"), reason="git not installed")
def test_cleanup_marks_repo_worktree_pruned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "r"
    _git_init_commit(repo)
    wt = tmp_path / "wt" / "x"
    wt.mkdir(parents=True)
    rid = uuid.uuid4()
    row = models.RepoWorktree(
        id=uuid.uuid4(),
        run_id=rid,
        base_repo_path=str(repo.resolve()),
        worktree_path=str(wt.resolve()),
        branch_name=f"ao/{rid}",
        commit_sha=None,
        created_at=utc_now(),
        pruned_at=None,
    )
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = row

    def fake_run(cmd, **kwargs):
        assert "worktree" in cmd and "remove" in cmd
        return MagicMock(returncode=0, stderr="", stdout="")

    monkeypatch.setattr("agent_orchestrator.services.worktree_manager.subprocess.run", fake_run)

    settings = MagicMock(spec=Settings)
    msg = WorktreeManager.cleanup(session, rid, settings)
    assert "Removed worktree" in msg
    assert row.pruned_at is not None


def test_dispatch_claude_fails_without_git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    nogit = tmp_path / "nogit"
    nogit.mkdir()
    run_id = uuid.uuid4()
    art = tmp_path / "artifacts" / str(run_id)
    art.mkdir(parents=True)
    (art / "plan.md").write_text("# p\n", encoding="utf-8")
    (art / "context_pack.md").write_text("# c\n", encoding="utf-8")

    proj = models.Project(
        id=uuid.uuid4(),
        name="p",
        slug="p3",
        default_repo_path=str(nogit),
        settings_json={},
        created_at=utc_now(),
    )
    run = models.Run(
        id=run_id,
        project_id=proj.id,
        status="planned",
        phase="planned",
        task_path=str(tmp_path / "t.md"),
        repo_path=str(nogit.resolve()),
        max_iterations=5,
        iteration_count=0,
        selected_worker=None,
        artifact_root=str(art),
        metadata_json={},
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    settings = MagicMock(spec=Settings)
    settings.allow_skip_confirmations = True
    settings.enable_claude_worker = True
    settings.running_in_docker = False
    settings.allow_cli_workers_in_docker = False
    settings.claude_code_bin = "claude"
    settings.claude_code_extra_args = ""

    class _FakeClaude:
        kind = "claude"

        def is_enabled(self) -> bool:
            return True

        def check_available(self) -> tuple[bool, str]:
            return True, "ok"

        def run(self, invocation):
            raise AssertionError("should not run")

    monkeypatch.setattr("agent_orchestrator.services.run_ops.get_worker", lambda _a, _s: _FakeClaude())

    session = MagicMock()

    with pytest.raises(RuntimeError, match="require a git repository"):
        dispatch_run(session, run, "claude", settings=settings, yes=True)
