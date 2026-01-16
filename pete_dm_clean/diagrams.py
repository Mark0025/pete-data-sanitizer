from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from pyflowchart import Flowchart

from loaders import load_csv


@dataclass(frozen=True)
class DiagramResult:
    name: str
    out_dir: Path
    flow_txt: Path
    summary_md: Path
    created_at: str


def _norm(x: Any) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    return str(x).strip()


def _safe_slug(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")
    return s or "diagram"


def default_flowcharts_dir(uploads_dir: Path, company_id: str | None = None) -> Path:
    base = Path(uploads_dir) / "flowcharts"
    if company_id:
        return base / _safe_slug(company_id)
    return base


def summarize_inputs(uploads_dir: Path) -> list[str]:
    """
    Lightweight runtime summary used to annotate the diagram.
    Uses the same auto-detection logic: desired-outcome + contacts + template.
    """
    uploads_dir = Path(uploads_dir)
    # desired-outcome
    desired = next((p for p in uploads_dir.glob("*.csv") if "desired-outcome" in p.name.lower()), None)
    if desired is None:
        desired = next(iter(uploads_dir.glob("*.csv")), None)

    contacts = next((p for p in uploads_dir.glob("*.csv") if "contacts" in p.name.lower()), None)
    if contacts is None:
        # try any other csv
        contacts = None

    template = uploads_dir / "templates" / "Properties Template (15).xlsx"

    lines: list[str] = []
    if desired and desired.exists():
        df = load_csv(desired)
        lines.append(f"desired_outcome: {desired.name} rows={len(df)} cols={len(df.columns)}")
        if "Full Address" in df.columns:
            dup = int(df.duplicated(subset=["Full Address"]).sum())
            uniq = int(df["Full Address"].nunique())
            lines.append(f"desired_outcome: unique_addresses={uniq} duplicate_rows={dup}")
    else:
        lines.append("desired_outcome: (not found)")

    if contacts and contacts.exists():
        cdf = load_csv(contacts)
        lines.append(f"contacts: {contacts.name} rows={len(cdf)} cols={len(cdf.columns)}")
    else:
        lines.append("contacts: (not found)")

    if template.exists():
        try:
            tdf = pd.read_excel(template)
            lines.append(f"template: {template.name} cols={len(tdf.columns)}")
        except Exception:
            lines.append(f"template: {template.name} (read failed)")
    else:
        lines.append("template: (not found)")

    return lines


def generate_code_flowchart(code_path: Path) -> str:
    """
    Generate flowchart DSL (flowchart.js syntax) from Python source code.
    """
    code = Path(code_path).read_text(encoding="utf-8")
    fc = Flowchart.from_code(code)
    return fc.flowchart()


def annotate_flowchart_start(flowchart_text: str, summary_lines: list[str]) -> str:
    """
    Try to append summary info to the first start node label.
    """
    if not summary_lines:
        return flowchart_text

    # flowchart.js labels support newlines; use \n in label text
    annotation = "\\n" + "\\n".join(summary_lines)

    out_lines = flowchart_text.splitlines()
    for i, line in enumerate(out_lines):
        # typical: st=>start: Start
        if "=>start:" in line:
            out_lines[i] = line + annotation
            break
    return "\n".join(out_lines) + ("\n" if not flowchart_text.endswith("\n") else "")


def write_summary_md(code_path: Path, summary_lines: list[str]) -> str:
    md: list[str] = []
    md.append("## Pipeline diagram summary")
    md.append("")
    md.append(f"- **Code file**: `{code_path}`")
    md.append("")
    md.append("### Runtime input summary")
    md.append("")
    for ln in summary_lines:
        md.append(f"- {ln}")
    md.append("")
    md.append("### What this diagram is")
    md.append("")
    md.append("- This is a **code flow diagram** generated from the Python file using `pyflowchart`.")
    md.append("- It is annotated with a small **runtime summary** of your current input files in `uploads/`.")
    md.append("")
    return "\n".join(md).rstrip() + "\n"


def generate_acki_flow_from_run(run: dict[str, Any]) -> str:
    """
    Build a small, stable, Acki-style pipeline diagram from *runtime* step records.
    This avoids noisy file-level diagrams like "from __future__ import annotations".
    """
    steps = run.get("steps", [])
    summary = run.get("summary", {})

    def label(base: str, extra: str = "") -> str:
        s = base
        if extra:
            s += f"\\n{extra}"
        return s

    def step_status(name: str) -> str:
        for s in steps:
            if s.get("name") == name:
                return s.get("status", "")
        return ""

    # High-signal metrics
    m1 = f"unique_addresses={summary.get('staging_unique_addresses', '')}"
    m2 = f"rows={summary.get('staging_rows', '')}"
    m3 = f"dupes_eliminated={summary.get('desired_outcome_duplicate_rows_eliminated', '')}"
    status = summary.get("overall_status", "")
    reasons = summary.get("overall_reasons", [])
    if isinstance(reasons, list):
        reason_str = "; ".join([str(r) for r in reasons[:3]])
    else:
        reason_str = str(reasons) if reasons else ""

    # flowchart.js DSL
    lines = []
    lines.append(f"st=>start: {label('Start', m1)}")
    lines.append(f"i=>inputoutput: {label('Detect inputs', '')}")
    lines.append(f"l=>operation: {label('Load CSV/XLSX', m3)}")
    lines.append(f"p=>operation: {label('Build staging (dedupe + seller match)', m2)}")
    lines.append("o=>operation: Write exports + reports")
    if status:
        lines.append(f"x=>operation: End Status\\n{status}\\n{reason_str}")
        lines.append("e=>end: Done")
    else:
        lines.append("e=>end: Done")

    lines.append("")
    # edges
    if status:
        lines.append("st->i->l->p->o->x->e")
    else:
        lines.append("st->i->l->p->o->e")

    # status note (simple)
    status_bits = [
        f"load_desired={step_status('load_desired')}",
        f"load_contacts={step_status('load_contacts')}",
        f"build_staging={step_status('build_staging')}",
        f"write_outputs={step_status('write_outputs')}",
    ]
    lines.append("")
    lines.append(f"// statuses: {' '.join(status_bits)}")
    return "\n".join(lines).rstrip() + "\n"


def generate_acki_deep_flow(run: dict[str, Any], debug: dict[str, Any]) -> str:
    """
    Deep-dive Acki diagram: runtime pipeline + debug metrics.
    Intended for AI troubleshooting, generated only when debug report is enabled.
    """
    summary = run.get("summary", {})
    steps = run.get("steps", [])
    match = debug.get("address_match_rate") or {}
    coverage = debug.get("seller_coverage_pct") or {}
    missing_seller = int(debug.get("addresses_missing_seller_count", 0) or 0)
    desired_dupes = int(debug.get("desired_duplicate_rows", 0) or 0)
    status = summary.get("overall_status", "")
    reasons = summary.get("overall_reasons", [])
    if isinstance(reasons, list):
        reason_str = "; ".join([str(r) for r in reasons[:5]])
    else:
        reason_str = str(reasons) if reasons else ""

    def step_info(name: str) -> str:
        for s in steps:
            if s.get("name") == name:
                return f"{s.get('status','')} {s.get('duration_ms','')}ms"
        return ""

    # keep annotations short
    lines = []
    lines.append("st=>start: Start")
    lines.append(f"i=>inputoutput: Detect inputs\\n{step_info('load_desired')}")
    lines.append(f"l=>operation: Load files\\ndesired_dupe_rows={desired_dupes}\\n{step_info('load_contacts')}")
    lines.append(
        "m=>operation: Match addresses (staging vs contacts)\\n"
        + f"match_pct={match.get('pct','')} matched={match.get('matched_in_contacts','')}/{match.get('total_staging','')}"
    )
    lines.append(
        "s=>operation: Seller coverage\\n"
        + f"Seller={coverage.get('Seller')}% Seller2={coverage.get('Seller2')}% Seller3={coverage.get('Seller3')}%"
    )
    lines.append(f"z=>operation: Missing sellers\\nmissing_count={missing_seller}")
    lines.append(
        "o=>operation: Write exports + reports\\n"
        + f"rows={summary.get('staging_rows','')} unique={summary.get('staging_unique_addresses','')}\\n{step_info('write_outputs')}"
    )
    if status:
        lines.append(f"x=>operation: End Status\\n{status}\\n{reason_str}")
    lines.append("e=>end: Done")
    lines.append("")
    if status:
        lines.append("st->i->l->m->s->z->o->x->e")
    else:
        lines.append("st->i->l->m->s->z->o->e")

    # add a small sample block as comments (keeps diagram parsable)
    sample_n = int(debug.get("sample_n", 25) or 25)
    no_match = debug.get("address_no_match_sample") or []
    if no_match:
        lines.append("")
        lines.append(f"// sample_no_match (first {min(sample_n, len(no_match))})")
        for a in no_match[:sample_n]:
            lines.append(f"// - {a}")

    miss = debug.get("addresses_missing_seller_sample") or []
    if miss:
        lines.append("")
        lines.append(f"// sample_missing_seller (first {min(sample_n, len(miss))})")
        for a in miss[:sample_n]:
            lines.append(f"// - {a}")

    collisions = debug.get("top_collision_rows") or []
    if collisions:
        lines.append("")
        lines.append(f"// top_collision_rows (first {min(sample_n, len(collisions))})")
        for r in collisions[:sample_n]:
            lines.append(f"// - {r}")

    gp = debug.get("top_global_phone_reuse") or []
    if gp:
        lines.append("")
        lines.append(f"// top_global_phone_reuse (first {min(sample_n, len(gp))})")
        for r in gp[:sample_n]:
            lines.append(f"// - {r}")

    ge = debug.get("top_global_email_reuse") or []
    if ge:
        lines.append("")
        lines.append(f"// top_global_email_reuse (first {min(sample_n, len(ge))})")
        for r in ge[:sample_n]:
            lines.append(f"// - {r}")

    return "\n".join(lines).rstrip() + "\n"


def generate_pipeline_diagram(
    *,
    uploads_dir: Path = Path("uploads"),
    code_path: Path = Path("build_staging.py"),
    name: str | None = None,
) -> DiagramResult:
    uploads_dir = Path(uploads_dir)
    out_dir = default_flowcharts_dir(uploads_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    created_at = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    diagram_name = _safe_slug(name or f"pipeline_{Path(code_path).stem}_{created_at}")

    summary_lines = summarize_inputs(uploads_dir)
    flow = generate_code_flowchart(code_path)
    flow = annotate_flowchart_start(flow, summary_lines)

    flow_txt = out_dir / f"{diagram_name}.flow.txt"
    summary_md = out_dir / f"{diagram_name}.summary.md"

    flow_txt.write_text(flow, encoding="utf-8")
    summary_md.write_text(write_summary_md(code_path, summary_lines), encoding="utf-8")

    return DiagramResult(
        name=diagram_name,
        out_dir=out_dir,
        flow_txt=flow_txt,
        summary_md=summary_md,
        created_at=created_at,
    )

