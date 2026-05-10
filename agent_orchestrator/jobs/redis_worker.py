from __future__ import annotations

import time

import redis

from agent_orchestrator.settings import get_settings


def run_worker_loop() -> None:
    """V1 stub: optionally block on Redis; real async execution deferred."""
    s = get_settings()
    r = redis.Redis.from_url(s.redis_url, socket_connect_timeout=2)
    r.ping()
    if not s.enable_redis_job_worker:
        print("Redis OK; ENABLE_REDIS_JOB_WORKER=false — exiting (stub).")
        return
    print("Listening on ao:jobs (stub processor)...")
    while True:
        item = r.brpop("ao:jobs", timeout=5)
        if item:
            _key, payload = item
            print(f"stub job: {payload!r}")
        time.sleep(0.1)
