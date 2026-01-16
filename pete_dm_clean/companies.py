from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _companies_path(uploads_dir: Path) -> Path:
    return Path(uploads_dir) / "companies.json"


def load_companies(uploads_dir: Path) -> dict[str, dict[str, Any]]:
    """
    Returns mapping: company_id -> { "name": str, "created_at": str? }
    """
    p = _companies_path(uploads_dir)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8") or "{}")
    if not isinstance(data, dict):
        return {}
    # normalize
    out: dict[str, dict[str, Any]] = {}
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, dict):
            out[k] = v
    return out


def save_companies(uploads_dir: Path, companies: dict[str, dict[str, Any]]) -> None:
    p = _companies_path(uploads_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(companies, indent=2, sort_keys=True), encoding="utf-8")


def new_company_id() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True)
class CompanyPaths:
    company_root: Path
    inputs_dir: Path
    templates_dir: Path
    outputs_dir: Path
    runs_dir: Path
    flowcharts_dir: Path


def company_paths(*, uploads_dir: Path, company_id: str) -> CompanyPaths:
    """
    All company-scoped persistence paths.

    - Inputs/outputs are scoped under uploads/companies/<company_id>/
    - Runs are scoped under uploads/runs/<company_id>/
    - Flowcharts are scoped under uploads/flowcharts/<company_id>/ (per rule)
    """
    uploads_dir = Path(uploads_dir)
    cid = company_id.strip()
    root = uploads_dir / "companies" / cid
    inputs_dir = root / "inputs"
    templates_dir = inputs_dir / "templates"
    outputs_dir = root / "outputs"
    runs_dir = uploads_dir / "runs" / cid
    flowcharts_dir = uploads_dir / "flowcharts" / cid
    return CompanyPaths(
        company_root=root,
        inputs_dir=inputs_dir,
        templates_dir=templates_dir,
        outputs_dir=outputs_dir,
        runs_dir=runs_dir,
        flowcharts_dir=flowcharts_dir,
    )


def ensure_company_dirs(paths: CompanyPaths) -> None:
    paths.inputs_dir.mkdir(parents=True, exist_ok=True)
    paths.templates_dir.mkdir(parents=True, exist_ok=True)
    paths.outputs_dir.mkdir(parents=True, exist_ok=True)
    paths.runs_dir.mkdir(parents=True, exist_ok=True)
    paths.flowcharts_dir.mkdir(parents=True, exist_ok=True)

