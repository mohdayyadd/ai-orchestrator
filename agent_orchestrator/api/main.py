from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_orchestrator.db import models
from agent_orchestrator.db.session import get_session_factory
from agent_orchestrator.services import run_ops
from agent_orchestrator.services.run_ops import utc_now
from agent_orchestrator.services.worktree_manager import get_active_repo_worktree
from agent_orchestrator.settings import get_settings

app = FastAPI(title="Agent Orchestrator", version="0.1.0")


def get_db() -> Session:
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class CreateRunBody(BaseModel):
    task_path: str
    repo_path: str


@app.post("/runs")
def api_create_run(body: CreateRunBody, db: Session = Depends(get_db)) -> dict[str, str]:
    s = get_settings()
    run = run_ops.create_run_record(
        db,
        task_file=Path(body.task_path),
        repo_path=Path(body.repo_path),
        settings=s,
    )
    db.commit()
    return {"run_id": str(run.id), "artifact_root": run.artifact_root}


@app.get("/runs")
def api_list_runs(limit: int = 50, db: Session = Depends(get_db)) -> list[dict[str, str]]:
    rows = db.execute(select(models.Run).order_by(models.Run.created_at.desc()).limit(limit)).scalars().all()
    return [
        {
            "id": str(r.id),
            "status": r.status,
            "phase": r.phase,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@app.get("/runs/{run_id}")
def api_get_run(run_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    rid = uuid.UUID(run_id)
    r = db.execute(select(models.Run).where(models.Run.id == rid)).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "run not found")
    wt = get_active_repo_worktree(db, rid)
    return {
        "id": str(r.id),
        "status": r.status,
        "phase": r.phase,
        "selected_worker": r.selected_worker or "",
        "artifact_root": r.artifact_root,
        "repo_path": r.repo_path,
        "worktree_path": wt.worktree_path if wt else "",
        "worktree_branch": wt.branch_name if wt else "",
    }


@app.post("/runs/{run_id}/plan")
def api_plan(run_id: str, db: Session = Depends(get_db)) -> dict[str, str | bool]:
    s = get_settings()
    rid = uuid.UUID(run_id)
    r = run_ops.load_run(db, rid)
    if not r:
        raise HTTPException(404, "run not found")
    ok, msg = run_ops.plan_run(db, r, s)
    db.commit()
    return {"ok": ok, "message": msg}


class DispatchBody(BaseModel):
    agent: str = "mock"
    yes: bool = False


@app.post("/runs/{run_id}/dispatch")
def api_dispatch(run_id: str, body: DispatchBody, db: Session = Depends(get_db)) -> dict[str, str]:
    s = get_settings()
    rid = uuid.UUID(run_id)
    r = run_ops.load_run(db, rid)
    if not r:
        raise HTTPException(404, "run not found")
    run_ops.dispatch_run(db, r, body.agent, settings=s, yes=body.yes)
    db.commit()
    return {"status": "dispatched"}


@app.post("/runs/{run_id}/review")
def api_review(run_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    rid = uuid.UUID(run_id)
    r = run_ops.load_run(db, rid)
    if not r:
        raise HTTPException(404, "run not found")
    run_ops.review_run(db, r)
    db.commit()
    return {"status": "reviewed"}


class ApproveBody(BaseModel):
    approval_id: str | None = None
    approve: bool = True


@app.post("/runs/{run_id}/approve")
def api_approve(run_id: str, body: ApproveBody, db: Session = Depends(get_db)) -> dict[str, str]:
    """Resolve a pending approval row (minimal V1: mark latest pending as approved)."""
    rid = uuid.UUID(run_id)
    r = run_ops.load_run(db, rid)
    if not r:
        raise HTTPException(404, "run not found")
    q = select(models.Approval).where(models.Approval.run_id == rid, models.Approval.status == "pending")
    if body.approval_id:
        q = q.where(models.Approval.id == uuid.UUID(body.approval_id))
    ap = db.execute(q.order_by(models.Approval.requested_at.desc()).limit(1)).scalars().first()
    if not ap:
        return {"status": "no_pending_approval"}
    ap.status = "approved" if body.approve else "rejected"
    ap.resolved_at = utc_now()
    ap.resolved_by = "api"
    db.commit()
    return {"status": ap.status}


@app.get("/runs/{run_id}/artifacts")
def api_artifacts(run_id: str, db: Session = Depends(get_db)) -> dict[str, list[dict[str, str]]]:
    rid = uuid.UUID(run_id)
    rows = db.execute(select(models.Artifact).where(models.Artifact.run_id == rid)).scalars().all()
    return {"artifacts": [{"kind": a.kind, "path": a.relative_path} for a in rows]}


@app.get("/ecc/status")
def ecc_status() -> dict[str, str]:
    from agent_orchestrator.ecc.service import ecc_status as s

    return {"message": s()}


@app.post("/ecc/sync")
def ecc_sync() -> dict[str, str]:
    from agent_orchestrator.ecc.service import ecc_sync as s

    return {"message": s()}


@app.get("/ecc/components")
def ecc_components() -> dict[str, list[str]]:
    from agent_orchestrator.ecc.service import ecc_list_components

    return {"lines": ecc_list_components()}


@app.get("/ecc/components/{name}")
def ecc_component(name: str) -> dict[str, str]:
    from agent_orchestrator.ecc.service import ecc_inspect

    return {"detail": ecc_inspect(name)}


@app.post("/ecc/recommend/{run_id}")
def ecc_rec(run_id: str) -> dict[str, str]:
    from agent_orchestrator.ecc.service import ecc_recommend

    return {"message": ecc_recommend(uuid.UUID(run_id))}


@app.post("/ecc/apply/{run_id}")
def ecc_ap(run_id: str, component: str, yes: bool = False) -> dict[str, str]:
    from agent_orchestrator.ecc.service import ecc_apply

    return {"message": ecc_apply(uuid.UUID(run_id), component, yes=yes)}


@app.post("/ecc/security-scan")
def ecc_scan() -> dict[str, str]:
    from agent_orchestrator.ecc.service import ecc_security_scan

    return {"message": ecc_security_scan()}


@app.get("/obsidian/status")
def obs_status() -> dict[str, str]:
    from agent_orchestrator.obsidian.service import obsidian_status

    return {"message": obsidian_status()}


@app.post("/obsidian/init-vault")
def obs_init() -> dict[str, str]:
    from agent_orchestrator.obsidian.service import obsidian_init_vault

    return {"message": obsidian_init_vault()}


@app.post("/obsidian/sync-run/{run_id}")
def obs_sync(run_id: str) -> dict[str, str]:
    from agent_orchestrator.obsidian.service import sync_run

    return {"message": sync_run(uuid.UUID(run_id))}


@app.post("/obsidian/write-run-summary/{run_id}")
def obs_ws(run_id: str) -> dict[str, str]:
    from agent_orchestrator.obsidian.service import write_run_summary

    return {"message": write_run_summary(uuid.UUID(run_id))}


@app.post("/obsidian/write-decision/{run_id}")
def obs_wd(run_id: str) -> dict[str, str]:
    from agent_orchestrator.obsidian.service import write_decision

    return {"message": write_decision(uuid.UUID(run_id))}


@app.post("/obsidian/write-learning/{run_id}")
def obs_wl(run_id: str) -> dict[str, str]:
    from agent_orchestrator.obsidian.service import write_learning

    return {"message": write_learning(uuid.UUID(run_id))}


@app.get("/obsidian/search")
def obs_search(q: str) -> dict[str, list[str]]:
    from agent_orchestrator.obsidian.service import search_notes

    return {"hits": search_notes(q)}
