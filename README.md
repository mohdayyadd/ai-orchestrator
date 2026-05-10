# AI Agent Orchestrator

Private, Docker-friendly orchestration for coding agents. **Postgres** is the system of record; **Redis** is present for queues and health checks (V1 runs most steps synchronously). Real **Claude Code** / **Codex** / **Cursor** workers are **thin subprocess wrappers** intended to run on the **host** where your subscription CLI is authenticated — do not mount auth directories into Docker.

## Quick start (Docker)

1. Clone this repository (private GitHub is fine).
2. `cp .env.example .env` and adjust if needed.
3. `docker compose up --build`
4. In another terminal:
   - `docker compose exec app alembic upgrade head`
   - `docker compose exec app ao init`
   - `docker compose exec app ao create-run --task /workspace/tasks/example_task.md --repo /workspace/repos/example-repo`
   - `docker compose exec app ao plan <run_id>`
   - `docker compose exec app ao dispatch <run_id> --agent mock`
   - `docker compose exec app ao review <run_id>`
   - `docker compose exec app ao status <run_id>`

Container **default** for real CLIs: use **MockWorker**. For subscription CLIs, use **hybrid host-runner** (below).

## Hybrid host-runner (Claude / Codex subscription CLIs)

Keep Postgres/Redis/API in Docker, run the CLI on your machine so `claude` / `codex` use your existing login (no API keys, no auth bind-mounts).

1. `docker compose up --build`
2. On the host: `uv sync` then set `DATABASE_URL=postgresql+psycopg://orchestrator:orchestrator@127.0.0.1:5432/orchestrator` (and `REDIS_URL=redis://127.0.0.1:6379/0`) in `.env`.
3. `alembic upgrade head` / `ao init` using host venv.
4. Use host paths for task/repo, e.g.  
   `uv run ao create-run --task ./workspace/tasks/example_task.md --repo ./workspace/repos/example-repo`  
   `uv run ao plan <run_id>`  
   `uv run ao dispatch <run_id> --agent claude` (after enabling `ENABLE_CLAUDE_WORKER=true`)

Do **not** mount `~/.claude`, `~/.codex`, or other credential directories into the app container by default.

## Environment validation

```bash
docker compose exec app ao doctor
# or on host:
uv run ao doctor
```

## Windows notes

- Prefer a UTF-8 terminal (Windows Terminal defaults are fine). The demo LangGraph node uses ASCII-only output so `ao` / tests do not depend on Unicode symbols in the console.
- If `uv` is not installed, use `py -3.11 -m pip install -e ".[dev]"` from the repo root.

- No auto-push, auto-merge, or destructive allowlisted commands in worker/test paths without explicit approvals.
- Real-agent dispatch prompts for confirmation unless configured otherwise (see `.env.example`).

## License

Private / internal use — add your own `LICENSE` if needed.
