"""Skip trace results → Pete CRM 129-column format converter.

Reads flat skip trace XLSX/CSV files (from Real Estate API or similar providers)
and maps them to Pete Properties Import format, ready for upload.

Uses the same PETE_COLUMNS schema and conventions as the skipTracing project's
pete_format.py — one row per input address, sellers mapped to Seller/Seller2/Seller3.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import Workbook
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Pete 129-column schema (canonical order)
# ---------------------------------------------------------------------------

PETE_COLUMNS: list[str] = [
    "External Id", "Full Address", "Street", "City", "Status", "State", "Campaign", "Zip Code",
    "Seller", "Seller Email", "Seller Phone", "Temperature", "Seller Email2", "Motivation", "Phase",
    "Seller Phone2", "Seller Email3", "Peer Review", "Seller Phone3", "Approved", "Seller Email4",
    "Needs Financing", "Seller Phone4", "Is Disposition Marketing Started", "Seller Email5",
    "Creation Date", "Seller Phone5", "Legal Entity", "Property Type", "Disposition Strategy", "Tags",
    "Latitude", "Seller2", "Longitude", "Seller3", "Seller2 Email", "Seller3 Email", "Seller2 Phone",
    "Seller3 Phone", "Seller2 Email2", "Seller3 Email2", "Seller2 Phone2", "Seller3 Phone2",
    "Seller2 Email3", "Seller3 Email3", "Is Vacant", "Seller2 Phone3", "Bedrooms", "Seller3 Phone3",
    "Bathrooms", "Seller2 Email4", "Garages", "Seller3 Email4", "Fireplaces", "Seller2 Phone4",
    "Zillow URL", "Seller3 Phone4", "Year Built", "Seller2 Email5", "Size", "Seller3 Email5",
    "Lead Origin", "Seller2 Phone5", "Appointment Status", "Seller3 Phone5", "Estimated Rehab",
    "After Repair Value", "Wholesale Price", "Asking Price", "Purchase Price", "Monthly Insurance",
    "Current Rent", "Market Rent Rate", "Other Costs", "Offer Amount", "Offer Made", "Offer Made Date",
    "Purchase Contract Date", "Contracted Purchase Date", "Lease Start Date", "Lease End Date",
    "Property Taxes", "Is Manual Creation", "County Treasurer Account", "Before Pictures Complete",
    "After Pictures Complete", "Is Scope Complete", "Is Insured", "Keys Location", "Vacancy Date",
    "Rehab Start", "Rehab End", "Rehab Size", "Rehab Priority", "Purchase Date",
    "Purchase Commitment Received", "Purchase Commitment Received Date", "Is Purchase Closed",
    "Clear Title Date", "Commitment", "Settlement Statement", "Assignment Fee", "Sale Contract Date",
    "Contracted Sale Date", "Is Sale Closed", "Sale Date", "Sale Price", "Is Affidavit", "Agent Fees",
    "Advertised Wholesale Price", "Actual Rehab Cost", "Holding Costs", "Closing Costs", "Gross Profit",
    "Net Profit", "Purchase Costs", "All In Cost", "Estimated Profit", "Rental Description",
    "Estimated Mortgage Balance", "Estimated Mortgage Payment", "Is Sale Commitment Received",
    "Mortgage Company", "Sale Commitment Received Date", "Original Principal", "Listed Date",
    "Current Principal", "Mortgage P&I", "Auction Date",
]

# ---------------------------------------------------------------------------
# Pydantic config for the conversion
# ---------------------------------------------------------------------------


class SkipTraceConvertConfig(BaseModel):
    """User-facing options for skip trace → Pete conversion."""

    campaign: str = "Skip Trace"
    status: str = "New"
    phase: str = ""
    external_id_digits: int = Field(default=7, ge=6, le=32)
    export_prefix: str = "skiptrace.pete.clean"
    export_date_format: str = "%m.%d.%y"
    no_desktop_copy: bool = False


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConvertResult:
    out_xlsx: Path
    out_csv: Path
    seller_summary_csv: Path
    report_md: Path
    total_rows: int
    total_sellers: int
    skipped_rows: int
    input_rows: int
    rows_with_phone: int
    rows_with_email: int
    rows_with_phone2: int
    dnc_count: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe(val: Any) -> str:
    """Coerce a cell value to a clean string."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    s = str(val).strip()
    # strip trailing ".0" from numeric strings (zip codes, phones)
    if s.endswith(".0") and s.replace(".", "").replace("-", "").isdigit():
        s = s[:-2]
    return s


def _strip_zip(address: str) -> str:
    """Remove trailing ZIP from address string."""
    if not address:
        return ""
    return re.sub(r"\s*\d{5}(?:-\d{4})?\s*$", "", address).strip()


def _format_phone(raw: str) -> str:
    """Normalise phone to digits-only string."""
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    return digits


def _split_multi(val: str, sep: str = ";") -> list[str]:
    """Split a semicolon-delimited value, strip blanks."""
    if not val:
        return []
    return [v.strip() for v in val.split(sep) if v.strip()]


def _generate_external_ids(count: int, digits: int = 7) -> list[str]:
    """Generate *count* unique random numeric IDs of *digits* length."""
    rng = random.Random()
    low = 10 ** (digits - 1)
    high = (10**digits) - 1
    used: set[str] = set()
    ids: list[str] = []
    for _ in range(count):
        while True:
            v = str(rng.randint(low, high))
            if v not in used:
                used.add(v)
                ids.append(v)
                break
    return ids


# ---------------------------------------------------------------------------
# Core conversion
# ---------------------------------------------------------------------------


def _map_seller_fields(
    row: dict[str, str],
    prefix: str,
    name: str,
    phones: list[str],
    emails: list[str],
) -> None:
    """Populate Seller/Seller2/Seller3 columns in *row*."""
    row[prefix] = name
    for idx, email in enumerate(emails[:5], 1):
        col = f"{prefix} Email" if idx == 1 else f"{prefix} Email{idx}"
        row[col] = email
    for idx, phone in enumerate(phones[:5], 1):
        col = f"{prefix} Phone" if idx == 1 else f"{prefix} Phone{idx}"
        row[col] = _format_phone(phone)


def convert_skiptrace_df(df: pd.DataFrame, cfg: SkipTraceConvertConfig) -> list[dict[str, str]]:
    """Convert a skip trace DataFrame to Pete-format rows.

    Handles the flat skip trace xlsx schema where each row already has
    one person's data (``first_name``, ``phone``, ``all_phones``, etc.).

    The function groups rows by input address to produce **one Pete row per
    address** with up to 3 sellers, matching Petedatasanitizer behaviour.
    """
    # Normalise column names to lowercase for fuzzy matching
    df.columns = [c.strip().lower() for c in df.columns]

    # Build an address key for grouping
    def _addr_key(r: pd.Series) -> str:
        parts = [
            _safe(r.get("input_address", "")),
            _safe(r.get("input_city", "")),
            _safe(r.get("input_state", "")),
            _safe(r.get("input_zip", "")),
        ]
        return re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip().lower()

    df["_addr_key"] = df.apply(_addr_key, axis=1)

    groups = df.groupby("_addr_key", sort=False)
    row_count = len(groups)
    ext_ids = _generate_external_ids(row_count, cfg.external_id_digits)

    pete_rows: list[dict[str, str]] = []
    skipped = 0
    total_sellers = 0

    for idx, (_key, group) in enumerate(groups):
        first = group.iloc[0]

        street = _safe(first.get("input_address", ""))
        city = _safe(first.get("input_city", ""))
        state = _safe(first.get("input_state", ""))
        zip_code = _safe(first.get("input_zip", ""))

        if not street and not city:
            skipped += 1
            continue

        full_address = _strip_zip(" ".join(p for p in [street, city, state] if p))

        row: dict[str, str] = {col: "" for col in PETE_COLUMNS}
        row.update(
            {
                "External Id": ext_ids[idx],
                "Full Address": full_address,
                "Street": street,
                "City": city,
                "State": state,
                "Zip Code": zip_code,
                "Campaign": cfg.campaign,
                "Status": cfg.status,
                "Phase": cfg.phase,
                "Lead Origin": "Skip Trace",
                "Creation Date": datetime.now().strftime("%Y-%m-%d"),
            }
        )

        # Map up to 3 persons (rows in group) → Seller / Seller2 / Seller3
        prefixes = ["Seller", "Seller2", "Seller3"]
        for person_idx, (_, person_row) in enumerate(group.iterrows()):
            if person_idx >= 3:
                break

            first_name = _safe(person_row.get("first_name", ""))
            last_name = _safe(person_row.get("last_name", ""))
            name = f"{first_name} {last_name}".strip()
            if not name:
                name = _safe(person_row.get("full_name", ""))

            # Primary phone + all_phones
            primary_phone = _safe(person_row.get("phone", ""))
            all_phones_raw = _safe(person_row.get("all_phones", ""))
            phones = [primary_phone] if primary_phone else []
            for p in _split_multi(all_phones_raw):
                cleaned = _format_phone(p)
                if cleaned and cleaned not in [_format_phone(x) for x in phones]:
                    phones.append(p)

            # Primary email + all_emails
            primary_email = _safe(person_row.get("email", ""))
            all_emails_raw = _safe(person_row.get("all_emails", ""))
            emails = [primary_email] if primary_email else []
            for e in _split_multi(all_emails_raw):
                if e and e not in emails:
                    emails.append(e)

            _map_seller_fields(row, prefixes[person_idx], name, phones, emails)
            total_sellers += 1

        pete_rows.append(row)

    return pete_rows


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def load_skiptrace_file(path: Path | str) -> pd.DataFrame:
    """Load a skip trace XLSX or CSV into a DataFrame."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(path, engine="openpyxl")
    if suffix == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported file type: {suffix}")


def write_pete_outputs(
    rows: list[dict[str, str]],
    output_dir: Path,
    prefix: str,
    date_fmt: str,
) -> tuple[Path, Path]:
    """Write Pete-format XLSX and CSV. Returns (xlsx_path, csv_path)."""
    date_str = datetime.now().strftime(date_fmt)
    stem = f"{prefix}.{date_str}"

    output_dir.mkdir(parents=True, exist_ok=True)

    # CSV
    csv_path = output_dir / f"{stem}.csv"
    out_df = pd.DataFrame(rows, columns=PETE_COLUMNS)
    out_df.to_csv(csv_path, index=False)

    # XLSX
    xlsx_path = output_dir / f"{stem}.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(PETE_COLUMNS)
    for row in rows:
        ws.append([row.get(col, "") for col in PETE_COLUMNS])
    wb.save(xlsx_path)

    return xlsx_path, csv_path


def write_seller_summary(
    rows: list[dict[str, str]],
    output_dir: Path,
    prefix: str,
    date_fmt: str,
) -> Path:
    """Write a seller summary CSV — one row per seller with contact info."""
    date_str = datetime.now().strftime(date_fmt)
    path = output_dir / f"{prefix}.{date_str}.seller_summary.csv"

    summary_rows: list[dict[str, str]] = []
    for row in rows:
        for prefix_name in ("Seller", "Seller2", "Seller3"):
            name = row.get(prefix_name, "")
            if not name:
                continue
            phones = []
            emails = []
            for i in range(1, 6):
                pcol = f"{prefix_name} Phone" if i == 1 else f"{prefix_name} Phone{i}"
                ecol = f"{prefix_name} Email" if i == 1 else f"{prefix_name} Email{i}"
                if row.get(pcol):
                    phones.append(row[pcol])
                if row.get(ecol):
                    emails.append(row[ecol])
            summary_rows.append({
                "Full Address": row.get("Full Address", ""),
                "City": row.get("City", ""),
                "State": row.get("State", ""),
                "Zip Code": row.get("Zip Code", ""),
                "Seller Role": prefix_name,
                "Seller Name": name,
                "Phone 1": phones[0] if len(phones) > 0 else "",
                "Phone 2": phones[1] if len(phones) > 1 else "",
                "Phone 3": phones[2] if len(phones) > 2 else "",
                "Email 1": emails[0] if len(emails) > 0 else "",
                "Email 2": emails[1] if len(emails) > 1 else "",
                "Campaign": row.get("Campaign", ""),
                "Status": row.get("Status", ""),
                "External Id": row.get("External Id", ""),
            })

    pd.DataFrame(summary_rows).to_csv(path, index=False)
    return path


def write_conversion_report(
    input_df: pd.DataFrame,
    pete_rows: list[dict[str, str]],
    cfg: SkipTraceConvertConfig,
    output_dir: Path,
    prefix: str,
    date_fmt: str,
    input_filename: str = "",
) -> tuple[Path, dict[str, Any]]:
    """Write a markdown conversion report. Returns (path, stats_dict)."""
    date_str = datetime.now().strftime(date_fmt)
    path = output_dir / f"{prefix}.{date_str}.report.md"

    # Normalise columns for analysis
    cols = [c.strip().lower() for c in input_df.columns]
    df = input_df.copy()
    df.columns = cols

    total_input = len(df)
    has_addr = df["input_address"].notna() & (df["input_address"].astype(str).str.strip() != "")
    data_rows = has_addr.sum()
    empty_rows = total_input - data_rows

    # Analyse pete output
    s1 = sum(1 for r in pete_rows if r.get("Seller"))
    s2 = sum(1 for r in pete_rows if r.get("Seller2"))
    s3 = sum(1 for r in pete_rows if r.get("Seller3"))
    has_phone = sum(1 for r in pete_rows if r.get("Seller Phone"))
    has_phone2 = sum(1 for r in pete_rows if r.get("Seller Phone2"))
    has_email = sum(1 for r in pete_rows if r.get("Seller Email"))
    has_email2 = sum(1 for r in pete_rows if r.get("Seller Email2"))

    # DNC analysis from input
    dnc_col = "phone_do_not_call"
    dnc_count = 0
    if dnc_col in cols:
        dnc_vals = df.loc[has_addr, dnc_col]
        dnc_count = int((dnc_vals == 1.0).sum() | (dnc_vals.astype(str).str.strip() == "True").sum())

    # Phone type breakdown
    phone_type_col = "phone_type"
    type_counts: dict[str, int] = {}
    if phone_type_col in cols:
        for val in df.loc[has_addr, phone_type_col].dropna():
            t = str(val).strip().lower()
            type_counts[t] = type_counts.get(t, 0) + 1

    # Connected phones
    connected_col = "phone_is_connected"
    connected = 0
    disconnected = 0
    if connected_col in cols:
        conn_vals = df.loc[has_addr, connected_col]
        connected = int((conn_vals == 1.0).sum() | (conn_vals.astype(str).str.strip() == "True").sum())
        disconnected = int(data_rows - connected)

    stats = {
        "input_rows": total_input,
        "data_rows": data_rows,
        "empty_rows": empty_rows,
        "pete_rows": len(pete_rows),
        "sellers": s1,
        "sellers2": s2,
        "sellers3": s3,
        "has_phone": has_phone,
        "has_phone2": has_phone2,
        "has_email": has_email,
        "has_email2": has_email2,
        "dnc_count": dnc_count,
        "phone_types": type_counts,
        "connected": connected,
        "disconnected": disconnected,
    }

    lines = [
        f"# Skip Trace Conversion Report",
        f"",
        f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Input file**: {input_filename}",
        f"**Campaign**: {cfg.campaign}",
        f"**Status**: {cfg.status}",
        f"**Phase**: {cfg.phase or '(none)'}",
        f"",
        f"---",
        f"",
        f"## Input Summary",
        f"",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total input rows | {total_input} |",
        f"| Rows with data | {data_rows} |",
        f"| Empty / no-match rows (skipped) | {empty_rows} |",
        f"",
        f"## Output Summary",
        f"",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Pete rows created | {len(pete_rows)} |",
        f"| Seller (primary) | {s1} |",
        f"| Seller2 | {s2} |",
        f"| Seller3 | {s3} |",
        f"",
        f"## Contact Coverage",
        f"",
        f"| Field | Populated | Missing |",
        f"|-------|-----------|---------|",
        f"| Seller Phone | {has_phone} | {len(pete_rows) - has_phone} |",
        f"| Seller Phone2 | {has_phone2} | {len(pete_rows) - has_phone2} |",
        f"| Seller Email | {has_email} | {len(pete_rows) - has_email} |",
        f"| Seller Email2 | {has_email2} | {len(pete_rows) - has_email2} |",
        f"",
    ]

    if type_counts:
        lines += [
            f"## Phone Types",
            f"",
            f"| Type | Count |",
            f"|------|-------|",
        ]
        for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
            lines.append(f"| {t} | {c} |")
        lines.append("")

    if connected or disconnected:
        lines += [
            f"## Phone Connectivity",
            f"",
            f"| Status | Count |",
            f"|--------|-------|",
            f"| Connected | {connected} |",
            f"| Disconnected | {disconnected} |",
            f"",
        ]

    if dnc_count:
        lines += [
            f"## ⚠️ Do Not Call (DNC)",
            f"",
            f"**{dnc_count} out of {data_rows} records are flagged DNC.**",
            f"",
            f"These are included in the output but should NOT be cold-called.",
            f"Consider using mail or other outreach for DNC contacts.",
            f"",
        ]

    # Unmapped columns
    used = {
        "input_address", "input_city", "input_state", "input_zip",
        "first_name", "last_name", "full_name", "phone", "all_phones",
        "email", "all_emails", "input_first_name", "input_last_name",
        "input_middle_name", "input_unit", "input_mail_address",
        "input_mail_city", "input_mail_state", "input_mail_zip",
        "key", "match", "requestid", "statuscode", "statusmessage",
        "middle_name", "person_id",
    }
    unmapped = [c for c in cols if c not in used and not c.startswith("_")]
    if unmapped:
        lines += [
            f"## Unmapped Input Columns",
            f"",
            f"These columns exist in your input but are not mapped to Pete format:",
            f"",
        ]
        for c in unmapped:
            non_null = int(df[c].notna().sum())
            lines.append(f"- `{c}` ({non_null}/{total_input} populated)")
        lines.append("")

    path.write_text("\n".join(lines))
    return path, stats


def run_skiptrace_convert(
    input_path: Path,
    output_dir: Path,
    cfg: SkipTraceConvertConfig,
    desktop_copy_dir: Path | None = None,
    input_filename: str = "",
) -> ConvertResult:
    """Full pipeline: load → convert → write reports → optional desktop copy."""
    import shutil

    df = load_skiptrace_file(input_path)
    pete_rows = convert_skiptrace_df(df, cfg)

    xlsx_path, csv_path = write_pete_outputs(
        pete_rows, output_dir, cfg.export_prefix, cfg.export_date_format,
    )

    seller_summary_path = write_seller_summary(
        pete_rows, output_dir, cfg.export_prefix, cfg.export_date_format,
    )

    report_path, stats = write_conversion_report(
        df, pete_rows, cfg, output_dir, cfg.export_prefix,
        cfg.export_date_format, input_filename=input_filename,
    )

    # Desktop copy
    if desktop_copy_dir and not cfg.no_desktop_copy:
        desktop_copy_dir.mkdir(parents=True, exist_ok=True)
        for p in (xlsx_path, csv_path, seller_summary_path, report_path):
            shutil.copy2(p, desktop_copy_dir / p.name)

    return ConvertResult(
        out_xlsx=xlsx_path,
        out_csv=csv_path,
        seller_summary_csv=seller_summary_path,
        report_md=report_path,
        total_rows=len(pete_rows),
        total_sellers=sum(
            1 for row in pete_rows
            for pfx in ("Seller", "Seller2", "Seller3")
            if row.get(pfx, "")
        ),
        skipped_rows=stats["empty_rows"],
        input_rows=stats["input_rows"],
        rows_with_phone=stats["has_phone"],
        rows_with_email=stats["has_email"],
        rows_with_phone2=stats["has_phone2"],
        dnc_count=stats["dnc_count"],
    )
