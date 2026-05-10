# AI Agent Orchestrator

Private, Docker-friendly orchestration for coding agents. **Postgres** is the system of record; **Redis** is present for queues and health checks (V1 runs most steps synchronously). Real **Claude Code** / **Codex** / **Cursor** workers are **thin subprocess wrappers** intended to run on the **host** where your subscription CLI is authenticated — do not mount auth directories into Docker.

## Git worktree isolation

Before **every** `dispatch`, the orchestrator creates (or reuses) a **dedicated git worktree** when `run.repo_path` is a git repository:

- **Base repo**: path stored on the run as `repo_path` (the original checkout).
- **Worktree directory**: `WORKTREES_DIR/<run_id>` (default `.agent_worktrees/<run_id>` on the host, or `/workspace/.agent_worktrees/<run_id>` in Docker when using the sample `.env`).
- **Branch**: `ao/<run_id>`.

The row is stored in **`repo_worktrees`**; **`WorkerInvocation.worktree_path`** is always this worktree path for that run (mock and real), never the original repo path for real workers.

**Claude / Codex / Cursor** dispatch **fails** if the target is not a git repo (no worktree can be created). **Mock** still runs against the plain directory if `repo_path` is not a git checkout (fallback only).

Remove a worktree after you are done:

```bash
ao cleanup-worktree <run_id>
```

`ao status <run_id>` prints the original **repo** path, active **worktree** path, and **branch** name.

Target repositories must be initialized with **`git init`** (and at least one commit) before dispatch if you want isolation.

## Quick start (Docker)

1. Clone this repository (private GitHub is fine).
2. `cp .env.example .env` and adjust if needed.
3. `docker compose up --build`
4. In another terminal:
   - `docker compose exec app alembic upgrade head`
   - `docker compose exec app ao init`
   - Ensure the example repo is a git repo, e.g.  
     `docker compose exec app sh -c "cd /workspace/repos/example-repo && git init && git add . && git commit -m init"`
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
4. Use host paths for task/repo (repo must be a **git** checkout for real workers), e.g.  
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

## Safety

- No auto-push, auto-merge, or destructive allowlisted commands in worker/test paths without explicit approvals.
- Real-agent dispatch prompts for confirmation unless configured otherwise (see `.env.example`).

## License

Private / internal use — add your own `LICENSE` if needed.
