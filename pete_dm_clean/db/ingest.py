from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from pete_dm_clean.db.models import Artifact, Company, Run
from pete_dm_clean.db.session import create_engine_if_enabled, get_sessionmaker, init_db


def _parse_dt(value: str) -> datetime:
    # Expected: "2026-01-15T00:20:16Z"
    v = (value or "").strip()
    if not v:
        return datetime.now(timezone.utc)
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _safe_text(v: Any) -> str:
    s = "" if v is None else str(v)
    return s.strip()


def _overall_status(run: dict[str, Any]) -> tuple[str, list[str]]:
    summary = (run.get("summary") or {}) if isinstance(run.get("summary"), dict) else {}
    # Prefer newer computed status if present (v0.0.6+ writes this in summary)
    status = _safe_text(summary.get("overall_status") or "")
    reasons = summary.get("overall_reasons") or []
    if status:
        try:
            reasons_list = [str(x) for x in (reasons if isinstance(reasons, list) else [])]
        except Exception:
            reasons_list = []
        return status, reasons_list

    # Fallback: derive from steps
    st = "OK"
    rs: list[str] = []
    for step in run.get("steps") or []:
        if isinstance(step, dict) and step.get("status") == "fail":
            st = "FAIL"
            rs.append(f"step_failed:{step.get('name')}")
    return st, rs


def _rel_path(path: str, uploads_dir: Path) -> str:
    """
    Store relative-to-uploads paths where possible to keep the DB portable across hosts.
    """
    p = Path(path) if path else None
    if not p:
        return ""
    try:
        resolved = p.resolve()
        root = Path(uploads_dir).resolve()
        rel = resolved.relative_to(root)
        return rel.as_posix()
    except Exception:
        return str(p)


def ingest_run_json(*, engine: Engine, uploads_dir: Path, run_json_path: Path) -> None:
    """
    Upsert a run record + artifacts into the DB.
    """
    run_json_path = Path(run_json_path)
    data = json.loads(run_json_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return

    run_id = _safe_text(data.get("run_id") or run_json_path.stem)
    created_at = _parse_dt(_safe_text(data.get("created_at") or ""))
    app_version = _safe_text(data.get("app_version") or "")

    inputs = data.get("inputs") if isinstance(data.get("inputs"), dict) else {}
    company_id = _safe_text(inputs.get("company_id") or "") or None
    company_name = _safe_text(inputs.get("company_name") or "")

    status, reasons = _overall_status(data)

    sm = get_sessionmaker(engine)
    with sm() as session:
        # Ensure schema exists (cheap idempotent safety)
        init_db(engine)

        if company_id:
            company = session.get(Company, company_id)
            if company is None:
                company = Company(
                    id=company_id,
                    name=company_name,
                    created_at=created_at,
                )
                session.add(company)
            elif company_name and company.name != company_name:
                company.name = company_name

        run = session.get(Run, run_id)
        reasons_json = json.dumps(reasons, ensure_ascii=False)
        run_json_rel = _rel_path(str(run_json_path), uploads_dir)
        if run is None:
            run = Run(
                id=run_id,
                company_id=company_id,
                created_at=created_at,
                app_version=app_version,
                overall_status=status,
                overall_reasons=reasons_json,
                run_json_path=run_json_rel,
            )
            session.add(run)
        else:
            run.company_id = company_id
            run.created_at = created_at
            run.app_version = app_version
            run.overall_status = status
            run.overall_reasons = reasons_json
            run.run_json_path = run_json_rel

        def upsert_artifacts(role: str, mapping: dict[str, Any]) -> None:
            for k, v in mapping.items():
                key = _safe_text(k)
                path = _safe_text(v)
                if not key or not path:
                    continue
                rel = _rel_path(path, uploads_dir)
                existing = session.execute(
                    select(Artifact).where(
                        Artifact.run_id == run_id,
                        Artifact.role == role,
                        Artifact.key == key,
                    )
                ).scalar_one_or_none()
                if existing is None:
                    session.add(Artifact(run_id=run_id, role=role, key=key, path=rel))
                else:
                    existing.path = rel

        if isinstance(data.get("inputs"), dict):
            upsert_artifacts("input", data["inputs"])
        if isinstance(data.get("outputs"), dict):
            upsert_artifacts("output", data["outputs"])

        # common diagnostics (best-effort)
        diag: dict[str, Any] = {}
        # RunTracker logs/debug live alongside run json, but they’re not always in outputs for old runs.
        for suffix, key in [
            (".log", "log"),
            (".summary.md", "summary_md"),
            (".debug.md", "debug_md"),
            (".debug.json", "debug_json"),
        ]:
            p = run_json_path.with_suffix(suffix)
            if p.exists():
                diag[key] = str(p)
        if diag:
            upsert_artifacts("diagnostic", diag)

        session.commit()


def maybe_ingest_run_json(*, uploads_dir: Path, run_json_path: Path) -> bool:
    """
    Convenience wrapper: only ingests if DB is enabled.
    Returns True if ingested, False otherwise.
    """
    engine = create_engine_if_enabled(uploads_dir=uploads_dir)
    if engine is None:
        return False
    ingest_run_json(engine=engine, uploads_dir=uploads_dir, run_json_path=run_json_path)
    return True

