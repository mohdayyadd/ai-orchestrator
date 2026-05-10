from __future__ import annotations

import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from agent_orchestrator.db import models
from agent_orchestrator.db.session import session_scope
from agent_orchestrator.settings import get_settings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ecc_status() -> str:
    s = get_settings()
    if not s.ecc_enabled:
        return "ECC disabled (ECC_ENABLED=false)"
    return f"ECC enabled; cache={s.ecc_cache_path}; hooks={s.ecc_allow_hooks}; npx={s.ecc_allow_npx}"


def ecc_sync() -> str:
    s = get_settings()
    if not s.ecc_enabled:
        return "ECC disabled"
    s.ecc_cache_path.mkdir(parents=True, exist_ok=True)
    url = s.ecc_source_url.strip()
    if not url:
        return "ECC_SOURCE_URL empty; created cache dir only"
    marker = s.ecc_cache_path / ".ecc_sync_log.txt"
    try:
        if (s.ecc_cache_path / ".git").exists():
            subprocess.run(
                ["git", "-C", str(s.ecc_cache_path), "pull", "--ff-only"],
                check=False,
                timeout=120,
            )
        else:
            subprocess.run(
                ["git", "clone", "--depth", "1", url, str(s.ecc_cache_path)],
                check=False,
                timeout=300,
            )
        marker.write_text(f"synced at {utc_now().isoformat()}\n", encoding="utf-8")
    except Exception as e:
        return f"sync error: {e}"
    with session_scope() as session:
        src = models.EccSource(
            id=uuid.uuid4(),
            source_url=url,
            last_synced_at=utc_now(),
            revision=None,
            cache_path=str(s.ecc_cache_path),
            metadata_json={},
        )
        session.add(src)
    return "ECC sync attempted (check git output / cache path)"


def _scan_components(cache: Path) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for p in cache.rglob("manifest.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            name = str(data.get("name", p.parent.name))
            kind = str(data.get("kind", "unknown"))
            out.append({"name": name, "kind": kind, "path": str(p.parent)})
        except Exception:
            out.append({"name": p.parent.name, "kind": "unknown", "path": str(p.parent)})
    return out


def ecc_list_components() -> list[str]:
    s = get_settings()
    if not s.ecc_enabled:
        return ["ECC disabled"]
    comps = _scan_components(s.ecc_cache_path)
    if not comps:
        return ["(no components found; run ao ecc sync)"]
    return [f"{c['name']}\t{c['kind']}\t{c['path']}" for c in comps]


def ecc_inspect(component: str) -> str:
    s = get_settings()
    if not s.ecc_enabled:
        return "ECC disabled"
    for c in _scan_components(s.ecc_cache_path):
        if c["name"] == component:
            return json.dumps(c, indent=2)
    return f"component not found: {component}"


def ecc_recommend(run_id: uuid.UUID) -> str:
    s = get_settings()
    if not s.ecc_enabled:
        return "ECC disabled"
    comps = _scan_components(s.ecc_cache_path)[:10]
    s = get_settings()
    path = Path(s.artifacts_dir) / str(run_id) / "ecc_recommendations.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"recommended": comps}, indent=2) + "\n", encoding="utf-8")
    return f"wrote {path}"


def ecc_apply(run_id: uuid.UUID, component: str, *, yes: bool) -> str:
    s = get_settings()
    if not s.ecc_enabled:
        return "ECC disabled"
    if not yes:
        return "Refusing apply without --yes"
    with session_scope() as session:
        run = session.execute(select(models.Run).where(models.Run.id == run_id)).scalar_one_or_none()
        if not run:
            return "run not found"
        comp_row = None
        for c in _scan_components(s.ecc_cache_path):
            if c["name"] == component:
                comp_row = c
                break
        if not comp_row:
            return "component not found"
        # Minimal component row linkage
        src = session.execute(select(models.EccSource)).scalars().first()
        if not src:
            src = models.EccSource(
                id=uuid.uuid4(),
                source_url="local",
                last_synced_at=None,
                revision=None,
                cache_path=str(s.ecc_cache_path),
                metadata_json={},
            )
            session.add(src)
            session.flush()
        ec = models.EccComponent(
            id=uuid.uuid4(),
            source_id=src.id,
            name=component,
            kind=comp_row.get("kind", "unknown"),
            path=comp_row["path"],
            manifest_json=comp_row,
            checksum=None,
        )
        session.add(ec)
        session.flush()
        session.add(
            models.EccComponentUsage(
                id=uuid.uuid4(),
                run_id=run_id,
                component_id=ec.id,
                usage_type="applied",
                detail_json={},
                created_at=utc_now(),
            )
        )
        artifact_root = run.artifact_root
    used = Path(artifact_root) / "ecc_components_used.json"
    used.write_text(json.dumps([{"name": component}], indent=2) + "\n", encoding="utf-8")
    return f"applied {component} (logged)"


def ecc_install(target: str, profile: str, *, dry_run: bool) -> str:
    s = get_settings()
    if not s.ecc_enabled:
        return "ECC disabled"
    if s.ecc_install_default_dry_run and not dry_run and not s.ecc_allow_npx:
        pass
    mode = "dry-run" if dry_run else "execute"
    with session_scope() as session:
        session.add(
            models.EccInstallation(
                id=uuid.uuid4(),
                target=target,
                profile=profile,
                dry_run=dry_run,
                status="planned" if dry_run else "requested",
                log_path=None,
                requested_at=utc_now(),
                completed_at=None,
            )
        )
    return f"ECC install ({mode}): target={target} profile={profile} (no home dir changes in V1 stub)"


def ecc_security_scan() -> str:
    s = get_settings()
    if not s.ecc_enabled:
        return "ECC disabled"
    report = s.ecc_cache_path / "security_scan_stub.md"
    report.write_text("# ECC security scan (stub)\n\nNo npx execution in V1.\n", encoding="utf-8")
    with session_scope() as session:
        session.add(
            models.EccSecurityScan(
                id=uuid.uuid4(),
                run_id=None,
                scan_kind="stub",
                result_json={"status": "stub"},
                report_path=str(report),
                created_at=utc_now(),
            )
        )
    return f"wrote {report}"
