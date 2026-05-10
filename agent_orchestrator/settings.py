from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env",),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+psycopg://orchestrator:orchestrator@localhost:5432/orchestrator",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")

    workspace_root: Path = Field(default=Path("/workspace"), alias="WORKSPACE_ROOT")
    artifacts_dir: Path = Field(default=Path(".agent_runs"), alias="ARTIFACTS_DIR")
    tasks_dir: Path = Field(default=Path("workspace/tasks"), alias="TASKS_DIR")

    running_in_docker: bool = Field(default=False, alias="RUNNING_IN_DOCKER")
    allow_cli_workers_in_docker: bool = Field(default=False, alias="ALLOW_CLI_WORKERS_IN_DOCKER")

    enable_claude_worker: bool = Field(default=False, alias="ENABLE_CLAUDE_WORKER")
    claude_code_bin: str = Field(default="claude", alias="CLAUDE_CODE_BIN")
    claude_code_extra_args: str = Field(default="", alias="CLAUDE_CODE_EXTRA_ARGS")
    enable_codex_worker: bool = Field(default=False, alias="ENABLE_CODEX_WORKER")
    codex_bin: str = Field(default="codex", alias="CODEX_BIN")
    codex_extra_args: str = Field(default="", alias="CODEX_EXTRA_ARGS")
    enable_cursor_worker: bool = Field(default=False, alias="ENABLE_CURSOR_WORKER")
    cursor_bin: str = Field(default="cursor", alias="CURSOR_BIN")

    allow_skip_confirmations: bool = Field(default=False, alias="ALLOW_SKIP_CONFIRMATIONS")

    ecc_enabled: bool = Field(default=False, alias="ECC_ENABLED")
    ecc_source_url: str = Field(default="", alias="ECC_SOURCE_URL")
    ecc_cache_path: Path = Field(default=Path("workspace/ecc"), alias="ECC_CACHE_PATH")
    ecc_allow_hooks: bool = Field(default=False, alias="ECC_ALLOW_HOOKS")
    ecc_allow_npx: bool = Field(default=False, alias="ECC_ALLOW_NPX")
    ecc_install_default_dry_run: bool = Field(default=True, alias="ECC_INSTALL_DEFAULT_DRY_RUN")

    obsidian_enabled: bool = Field(default=False, alias="OBSIDIAN_ENABLED")
    obsidian_vault_path: Path = Field(
        default=Path("workspace/obsidian-vault"), alias="OBSIDIAN_VAULT_PATH"
    )
    obsidian_project_folder: str = Field(default="AI-Orchestrator", alias="OBSIDIAN_PROJECT_FOLDER")
    obsidian_write_run_summaries: bool = Field(default=True, alias="OBSIDIAN_WRITE_RUN_SUMMARIES")
    obsidian_write_decisions: bool = Field(default=True, alias="OBSIDIAN_WRITE_DECISIONS")
    obsidian_write_learnings: bool = Field(default=True, alias="OBSIDIAN_WRITE_LEARNINGS")
    obsidian_read_project_notes: bool = Field(default=False, alias="OBSIDIAN_READ_PROJECT_NOTES")
    obsidian_max_context_notes: int = Field(default=5, alias="OBSIDIAN_MAX_CONTEXT_NOTES")
    obsidian_use_uri: bool = Field(default=False, alias="OBSIDIAN_USE_URI")
    obsidian_use_local_rest_api: bool = Field(default=False, alias="OBSIDIAN_USE_LOCAL_REST_API")
    obsidian_local_rest_api_url: str = Field(
        default="http://host.docker.internal:27123", alias="OBSIDIAN_LOCAL_REST_API_URL"
    )
    obsidian_local_rest_api_key: str = Field(default="", alias="OBSIDIAN_LOCAL_REST_API_KEY")

    enable_redis_job_worker: bool = Field(default=False, alias="ENABLE_REDIS_JOB_WORKER")

    @field_validator(
        "running_in_docker",
        "allow_cli_workers_in_docker",
        "enable_claude_worker",
        "enable_codex_worker",
        "enable_cursor_worker",
        "allow_skip_confirmations",
        "ecc_enabled",
        "ecc_allow_hooks",
        "ecc_allow_npx",
        "ecc_install_default_dry_run",
        "obsidian_enabled",
        "obsidian_write_run_summaries",
        "obsidian_write_decisions",
        "obsidian_write_learnings",
        "obsidian_read_project_notes",
        "obsidian_use_uri",
        "obsidian_use_local_rest_api",
        "enable_redis_job_worker",
        mode="before",
    )
    @classmethod
    def _coerce_bool(cls, v: object) -> bool:
        if v in (True, "true", "True", "1", 1):
            return True
        if v in (False, "false", "False", "0", 0, "", None):
            return False
        return bool(v)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
