from __future__ import annotations

from pathlib import Path

from agent_orchestrator.obsidian import config
from agent_orchestrator.settings import get_settings


def read_project_notes(max_notes: int) -> list[str]:
    s = get_settings()
    if not s.obsidian_read_project_notes:
        return []
    root = config.project_root() / "Projects"
    texts: list[str] = []
    for p in sorted(root.rglob("*.md")):
        texts.append(p.read_text(encoding="utf-8", errors="replace")[:8000])
        if len(texts) >= max_notes:
            break
    return texts
