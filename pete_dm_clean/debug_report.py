from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


def _norm(x: Any) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    return str(x).strip()


def normalize_address_key(address: Any) -> str:
    s = _norm(address).lower()
    if not s:
        return ""
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


@dataclass(frozen=True)
class DebugArtifacts:
    debug_json: Path
    debug_md: Path


def compute_debug_metrics(
    *,
    desired_df: pd.DataFrame | None,
    contacts_df: pd.DataFrame | None,
    staging_df: pd.DataFrame | None,
    addr_report_df: pd.DataFrame | None,
    phones_global_df: pd.DataFrame | None = None,
    emails_global_df: pd.DataFrame | None = None,
    sample_n: int = 25,
) -> dict[str, Any]:
    out: dict[str, Any] = {"sample_n": sample_n}

    if desired_df is not None:
        out["desired_rows"] = int(len(desired_df))
        if "Full Address" in desired_df.columns:
            out["desired_unique_addresses"] = int(desired_df["Full Address"].nunique(dropna=True))
            out["desired_duplicate_rows"] = int(desired_df.duplicated(subset=["Full Address"]).sum())

    if contacts_df is not None:
        out["contacts_rows"] = int(len(contacts_df))
        out["contacts_cols"] = int(len(contacts_df.columns))

    if staging_df is not None:
        out["staging_rows"] = int(len(staging_df))
        if "Full Address" in staging_df.columns:
            out["staging_unique_addresses"] = int(staging_df["Full Address"].nunique(dropna=True))

        # seller coverage
        def pct(col: str) -> float | None:
            if col not in staging_df.columns:
                return None
            s = staging_df[col].fillna("").astype(str).str.strip()
            return round(float((s != "").mean() * 100.0), 2)

        out["seller_coverage_pct"] = {
            "Seller": pct("Seller"),
            "Seller2": pct("Seller2"),
            "Seller3": pct("Seller3"),
        }

        if "Seller" in staging_df.columns:
            s = staging_df["Seller"].fillna("").astype(str).str.strip()
            missing_mask = s == ""
            out["addresses_missing_seller_count"] = int(missing_mask.sum())
            if "Full Address" in staging_df.columns:
                missing_addrs = staging_df.loc[missing_mask, "Full Address"].head(sample_n).tolist()
                out["addresses_missing_seller_sample"] = missing_addrs

    # address match rate (staging vs contacts)
    if staging_df is not None and contacts_df is not None:
        if "Full Address" in staging_df.columns and "associated_property_address_full" in contacts_df.columns:
            c = contacts_df.copy()
            c["_addr_key"] = c["associated_property_address_full"].map(normalize_address_key)
            contact_keys = set([k for k in c["_addr_key"].tolist() if _norm(k)])

            s = staging_df.copy()
            s["_addr_key"] = s["Full Address"].map(normalize_address_key)
            total = int(len(s))
            matched = int(s["_addr_key"].isin(contact_keys).sum())
            out["address_match_rate"] = {
                "total_staging": total,
                "matched_in_contacts": matched,
                "pct": round(float(matched / total * 100.0), 2) if total else 0.0,
            }
            # sample non-matches
            non = s.loc[~s["_addr_key"].isin(contact_keys), "Full Address"].head(sample_n).tolist()
            out["address_no_match_sample"] = non

    # collision highlights
    if addr_report_df is not None and not addr_report_df.empty:
        cols = [c for c in ["addr_key", "contacts_rows", "duplicate_phones_count", "duplicate_emails_count"] if c in addr_report_df.columns]
        out["top_collision_rows"] = addr_report_df[cols].head(sample_n).to_dict(orient="records")

    # global reuse highlights
    if phones_global_df is not None and not phones_global_df.empty:
        cols = [c for c in ["phone", "address_count", "occurrences", "unique_names"] if c in phones_global_df.columns]
        out["top_global_phone_reuse"] = phones_global_df[cols].head(sample_n).to_dict(orient="records")
    if emails_global_df is not None and not emails_global_df.empty:
        cols = [c for c in ["email", "address_count", "occurrences", "unique_names"] if c in emails_global_df.columns]
        out["top_global_email_reuse"] = emails_global_df[cols].head(sample_n).to_dict(orient="records")

    return out


def write_debug_report(
    *,
    debug_json_path: Path,
    debug_md_path: Path,
    run_id: str,
    metrics: dict[str, Any],
) -> DebugArtifacts:
    debug_json_path.parent.mkdir(parents=True, exist_ok=True)
    debug_md_path.parent.mkdir(parents=True, exist_ok=True)

    debug_json_path.write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")

    lines: list[str] = []
    lines.append("## Runtime debug report (deep-dive)")
    lines.append("")
    lines.append(f"- **run_id**: `{run_id}`")
    lines.append("")
    lines.append("### Key debug metrics (high-signal)")
    lines.append("")
    for k, v in metrics.items():
        if k in (
            "addresses_missing_seller_sample",
            "address_no_match_sample",
            "top_collision_rows",
            "top_global_phone_reuse",
            "top_global_email_reuse",
        ):
            continue
        lines.append(f"- **{k}**: {v}")
    lines.append("")

    if "addresses_missing_seller_sample" in metrics:
        lines.append("### Sample: addresses missing Seller")
        lines.append("")
        sample = metrics.get("addresses_missing_seller_sample") or []
        if sample:
            for a in sample:
                lines.append(f"- {a}")
        else:
            lines.append("_(none)_")
        lines.append("")

    if "address_no_match_sample" in metrics:
        lines.append("### Sample: staging addresses not found in contacts")
        lines.append("")
        sample = metrics.get("address_no_match_sample") or []
        if sample:
            for a in sample:
                lines.append(f"- {a}")
        else:
            lines.append("_(none)_")
        lines.append("")

    if "top_collision_rows" in metrics:
        lines.append("### Sample: top collision rows (phones/emails reused within address)")
        lines.append("")
        rows = metrics.get("top_collision_rows") or []
        if rows:
            for r in rows[: metrics.get("sample_n", 25)]:
                lines.append(f"- {r}")
        else:
            lines.append("_(none)_")
        lines.append("")

    if "top_global_phone_reuse" in metrics:
        lines.append("### Sample: phones reused across multiple addresses (global)")
        lines.append("")
        rows = metrics.get("top_global_phone_reuse") or []
        if rows:
            for r in rows[: metrics.get("sample_n", 25)]:
                lines.append(f"- {r}")
        else:
            lines.append("_(none)_")
        lines.append("")

    if "top_global_email_reuse" in metrics:
        lines.append("### Sample: emails reused across multiple addresses (global)")
        lines.append("")
        rows = metrics.get("top_global_email_reuse") or []
        if rows:
            for r in rows[: metrics.get("sample_n", 25)]:
                lines.append(f"- {r}")
        else:
            lines.append("_(none)_")
        lines.append("")

    debug_md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return DebugArtifacts(debug_json=debug_json_path, debug_md=debug_md_path)

