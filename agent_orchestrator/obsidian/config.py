from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from agent_orchestrator.settings import get_settings


class ObsidianNoteMeta(BaseModel):
    title: str
    run_id: str
    tags: list[str] = []


def vault_root() -> Path:
    s = get_settings()
    return Path(s.obsidian_vault_path)


def project_root() -> Path:
    s = get_settings()
    return vault_root() / s.obsidian_project_folder


def ensure_folders() -> None:
    base = project_root()
    for sub in (
        "Projects",
        "Runs",
        "Decisions",
        "Learnings",
        "Prompt-Patterns",
        "Research",
        "Agent-Performance",
        "Model-Routing",
    ):
        (base / sub).mkdir(parents=True, exist_ok=True)


def frontmatter(title: str, run_id: str, extra: dict[str, str] | None = None) -> str:
    lines = ["---", f"title: {title!r}", f"run_id: {run_id}"]
    if extra:
        for k, v in extra.items():
            lines.append(f"{k}: {v!r}")
    lines.append("---\n")
    return "\n".join(lines)
