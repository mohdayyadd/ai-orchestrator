from __future__ import annotations

from pathlib import Path

from agent_orchestrator.obsidian import config


def write_note(rel_path: str, body: str) -> Path:
    path = config.project_root() / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path
