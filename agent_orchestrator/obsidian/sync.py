from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from agent_orchestrator.db import models
from agent_orchestrator.db.session import session_scope
from agent_orchestrator.obsidian import config, writer
from agent_orchestrator.settings import get_settings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def obsidian_status() -> str:
    s = get_settings()
    if not s.obsidian_enabled:
        return "Obsidian disabled"
    return f"vault={s.obsidian_vault_path} project={s.obsidian_project_folder}"


def obsidian_init_vault() -> str:
    s = get_settings()
    if not s.obsidian_enabled:
        return "Obsidian disabled"
    config.ensure_folders()
    return f"initialized {config.project_root()}"


def _log_note(session, run_id: uuid.UUID, note_type: str, path: Path, title: str) -> None:
    s = get_settings()
    vault = Path(s.obsidian_vault_path).resolve()
    try:
        rel = str(path.resolve().relative_to(vault))
    except ValueError:
        rel = str(path)
    session.add(
        models.ObsidianNote(
            id=uuid.uuid4(),
            run_id=run_id,
            note_type=note_type,
            vault_path=str(s.obsidian_vault_path),
            obsidian_path=rel,
            title=title,
            tags_json=["ai-orchestrator"],
            metadata_json={},
            created_at=utc_now(),
        )
    )


def write_run_summary(run_id: uuid.UUID) -> str:
    s = get_settings()
    if not s.obsidian_enabled or not s.obsidian_write_run_summaries:
        return "Obsidian run summaries disabled"
    with session_scope() as session:
        run = session.execute(select(models.Run).where(models.Run.id == run_id)).scalar_one_or_none()
        if not run:
            return "run not found"
        rel = f"Runs/{run_id}.md"
        body = (
            config.frontmatter(f"Run {run_id}", str(run_id), {"status": run.status, "worker": str(run.selected_worker)})
            + f"\n## Summary\n\nArtifacts: `{run.artifact_root}`\n"
        )
        path = writer.write_note(rel, body)
        _log_note(session, run_id, "run_summary", path, f"Run {run_id}")
    sync = Path(run.artifact_root) / "obsidian_sync.md"
    sync.write_text(f"Synced run summary to Obsidian: {path}\n", encoding="utf-8")
    return str(path)


def write_decision(run_id: uuid.UUID) -> str:
    s = get_settings()
    if not s.obsidian_enabled or not s.obsidian_write_decisions:
        return "Obsidian decisions disabled"
    with session_scope() as session:
        run = session.execute(select(models.Run).where(models.Run.id == run_id)).scalar_one_or_none()
        if not run:
            return "run not found"
        rel = f"Decisions/{run_id}-decision.md"
        body = config.frontmatter("Decision log", str(run_id)) + "\n## Decision\n\n(placeholder)\n"
        path = writer.write_note(rel, body)
        _log_note(session, run_id, "decision", path, "Decision")
    return str(path)


def write_learning(run_id: uuid.UUID) -> str:
    s = get_settings()
    if not s.obsidian_enabled or not s.obsidian_write_learnings:
        return "Obsidian learnings disabled"
    with session_scope() as session:
        run = session.execute(select(models.Run).where(models.Run.id == run_id)).scalar_one_or_none()
        if not run:
            return "run not found"
        rel = f"Learnings/{run_id}-learning.md"
        body = config.frontmatter("Learning", str(run_id)) + "\n## What worked / failed\n\n(placeholder)\n"
        path = writer.write_note(rel, body)
        _log_note(session, run_id, "learning", path, "Learning")
    return str(path)


def sync_run(run_id: uuid.UUID) -> str:
    parts = [write_run_summary(run_id), write_decision(run_id), write_learning(run_id)]
    with session_scope() as session:
        run = session.execute(select(models.Run).where(models.Run.id == run_id)).scalar_one_or_none()
        if run:
            notes = session.execute(
                select(models.ObsidianNote).where(models.ObsidianNote.run_id == run_id)
            ).scalars().all()
            p = Path(run.artifact_root) / "obsidian_notes.json"
            p.write_text(
                json.dumps(
                    [{"path": n.obsidian_path, "type": n.note_type} for n in notes],
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
    return "\n".join(parts)


def search_notes(query: str) -> list[str]:
    s = get_settings()
    if not s.obsidian_enabled:
        return ["Obsidian disabled"]
    hits: list[str] = []
    root = config.project_root()
    q = query.lower()
    for p in root.rglob("*.md"):
        try:
            text = p.read_text(encoding="utf-8", errors="replace").lower()
            if q in text:
                hits.append(str(p.relative_to(config.vault_root())))
        except OSError:
            continue
        if len(hits) >= 20:
            break
    return hits or ["(no matches)"]


def open_run(run_id: uuid.UUID) -> str:
    return f"open-run: {run_id} (URI/REST not enabled; open vault folder manually)"
