from __future__ import annotations

from pydantic import BaseModel, Field


class ObsidianNoteRecord(BaseModel):
    vault_path: str
    obsidian_path: str
    title: str
    tags: list[str] = Field(default_factory=list)
