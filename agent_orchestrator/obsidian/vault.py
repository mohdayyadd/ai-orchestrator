from __future__ import annotations

from pathlib import Path

from agent_orchestrator.obsidian import config


def ensure_vault() -> Path:
    config.ensure_folders()
    return config.vault_root()
