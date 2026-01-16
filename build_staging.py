from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import csv
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from loaders import load_csv
from pete_dm_clean import __version__ as APP_VERSION
from pete_dm_clean.diagrams import default_flowcharts_dir, generate_acki_deep_flow, generate_acki_flow_from_run
from pete_dm_clean.logging import configure_logging, get_logger
from pete_dm_clean.debug_report import compute_debug_metrics, write_debug_report
from pete_dm_clean.generators import pete_template_generator
from pete_dm_clean.runtime import RunTracker, set_tracker


@dataclass(frozen=True)
class SellerContact:
    name: str
    emails: list[str]
    phones: list[str]
    is_likely_owner: bool


@dataclass(frozen=True)
class BuildResult:
    out_xlsx: Path
    out_csv: Path
    seller_summary_csv: Path
    report_json: Path
    report_addresses_csv: Path
    report_global_phones_csv: Path
    report_global_emails_csv: Path
    report_md: Path
    desktop_export_dir: Path | None
    copied_paths: list[Path]
    staging_rows: int
    staging_unique_addresses: int

def _norm(s: Any) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    return str(s).strip()


def normalize_address_for_join(address: Any) -> str:
    """
    Create a matching key between:
      - desired outcome `Full Address`: "4708 Ashland Ct Kansas City Mo 64127"
      - contacts `associated_property_address_full`: "4708 Ashland Ct, Kansas City, Mo 64127"
    """
    s = _norm(address).lower()
    if not s:
        return ""
    # remove punctuation -> spaces
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_zip(address: Any) -> str:
    s = _norm(address)
    m = re.search(r"(\d{5})(?:-\d{4})?\s*$", s)
    return m.group(1) if m else ""


def parse_us_address_simple(address: Any) -> tuple[str, str, str, str]:
    """
    Very small helper for contacts-only mode.
    Tries to parse: "street, city, ST 12345" into components.
    Returns: (street, city, state, zip)

    If parsing fails, returns ("", "", "", extracted_zip).
    """
    s = _norm(address)
    if not s:
        return ("", "", "", "")

    zip_code = extract_zip(s)
    # Prefer comma-separated format from contacts export.
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if len(parts) >= 3:
        street = parts[0]
        city = parts[1]
        state_zip = parts[2]
        toks = [t for t in re.split(r"\s+", state_zip.strip()) if t]
        state = toks[0] if toks else ""
        return (street, city, state, zip_code)

    # Fallback: best-effort split on last 2 tokens as state/zip
    toks = [t for t in re.split(r"\s+", s.strip()) if t]
    if len(toks) >= 3:
        state = toks[-2]
        zip_guess = toks[-1] if re.fullmatch(r"\d{5}(?:-\d{4})?", toks[-1] or "") else ""
        zip_code = zip_code or (zip_guess[:5] if zip_guess else "")
    return ("", "", state if state else "", zip_code)


def build_desired_from_contacts(contacts_df: pd.DataFrame) -> pd.DataFrame:
    """
    Contacts-only mode: derive a minimal "desired outcome" dataframe from contacts.
    This produces one row per unique associated_property_address_full.

    The output includes the minimal columns our staging builder expects.
    """
    # DealMachine contacts export uses associated_property_address_full, but allow fallbacks.
    address_col = None
    for c in [
        "associated_property_address_full",
        "Full Address",
        "property_address_full",
        "property_address",
        "address_full",
        "address",
    ]:
        if c in contacts_df.columns:
            address_col = c
            break
    if address_col is None:
        cols_preview = ", ".join([str(c) for c in list(contacts_df.columns)[:12]])
        raise ValueError(
            "contacts CSV is missing an address column needed for contacts-only mode. "
            "Expected 'associated_property_address_full' (DealMachine contacts export). "
            f"Found columns: {cols_preview}"
        )

    rows: list[dict[str, Any]] = []
    for addr in contacts_df[address_col].dropna().astype(str).tolist():
        addr_s = _norm(addr)
        if not addr_s:
            continue
        street, city, state, zip_code = parse_us_address_simple(addr_s)
        rows.append(
            {
                "External Id": "",
                "Full Address": addr_s,
                "Property Street": street,
                "Property City": city,
                "Property State": state,
                "Property ZIP": zip_code,
                "Status": "New",
                "Campaign": "Deal Machine",
                "Phase": "Lead",
            }
        )

    if not rows:
        # no addresses -> empty
        return pd.DataFrame(columns=["External Id", "Full Address", "Property Street", "Property City", "Property State", "Property ZIP", "Status", "Campaign", "Phase"])

    df = pd.DataFrame(rows)
    # Deduplicate to one row per address
    df = df.drop_duplicates(subset=["Full Address"]).reset_index(drop=True)
    return df


def _csv_header_has_column(path: Path, col_name: str) -> bool:
    """
    Cheap header sniff without pandas to pick the right contacts CSV in contacts-only mode.
    """
    try:
        with Path(path).open("r", encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, [])
        header_norm = {h.strip() for h in header}
        return col_name in header_norm
    except Exception:
        return False

def coalesce(*values: Any) -> str:
    for v in values:
        sv = _norm(v)
        if sv:
            return sv
    return ""


def _unique_nonempty(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        s = _norm(v)
        if not s:
            continue
        key = s.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _is_likely_owner(flags: Any) -> bool:
    s = _norm(flags).lower()
    return "likely owner" in s


def normalize_phone(phone: Any) -> str:
    """
    Normalize phone numbers for output + duplicate detection.

    Goals:
    - return digits only (no punctuation)
    - strip leading country code "1" when present (11 digits)
    - avoid pandas float artifacts like "5551112222.0"
    """
    if phone is None or (isinstance(phone, float) and pd.isna(phone)):
        return ""

    # Common failure mode: phone parsed as float -> "5551112222.0"
    if isinstance(phone, int):
        s_raw = str(phone)
    elif isinstance(phone, float):
        # If it’s integer-like, keep the integer digits (avoids ".0").
        s_raw = str(int(phone)) if phone.is_integer() else str(phone)
    else:
        s_raw = str(phone).strip()

    m = re.fullmatch(r"(\d+)\.0", s_raw)
    if m:
        s_raw = m.group(1)

    s = re.sub(r"\D+", "", s_raw)
    if len(s) == 11 and s.startswith("1"):
        s = s[1:]
    return s


def _unique_phones(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        p = normalize_phone(v)
        if not p:
            continue
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def normalize_phone_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize any "*Phone*" columns to digits-only strings.

    This prevents common spreadsheet/Pandas float artifacts like "5551112222.0"
    from leaking into exports.
    """
    phone_cols = [c for c in df.columns if "Phone" in str(c)]
    if not phone_cols:
        return df
    out = df.copy()
    for c in phone_cols:
        out[c] = out[c].map(normalize_phone)
    return out


def sanitize_for_import(df: pd.DataFrame) -> pd.DataFrame:
    """
    Make exports safer for naive CSV/XLSX importers.

    Rule:
    - Replace commas in cell values with spaces (prevents delimiter confusion in weak importers)
    - Replace newlines/tabs with spaces
    - Preserve blanks as blanks (avoid "nan")

    Notes:
    - This is applied only to the final import sheet (staging_df), not diagnostic reports.
    """
    if df.empty:
        return df

    out = df.copy()
    for c in out.columns:
        # Skip numeric dtype columns entirely; most import templates are stringy anyway.
        # When pandas inferred numeric, converting to string can introduce ".0" artifacts.
        if pd.api.types.is_numeric_dtype(out[c]):
            continue

        def fix(v: Any) -> str:
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return ""
            s = str(v)
            if not s:
                return ""
            s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
            s = s.replace(",", " ")
            s = re.sub(r"\s+", " ", s).strip()
            return s

        out[c] = out[c].map(fix)
    return out


def _mapping_entry(*, column: str, source: str, rule: str, example: str) -> dict[str, str]:
    return {"template_column": column, "source": source, "rule": rule, "example": example}


def _first_nonempty_example(df: pd.DataFrame, col: str, max_len: int = 80) -> str:
    if col not in df.columns or df.empty:
        return ""
    try:
        s = df[col]
    except Exception:
        return ""
    for v in s.tolist()[:500]:
        txt = _norm(v)
        if not txt:
            continue
        txt = txt.replace("\n", " ").strip()
        return (txt[: max_len - 1] + "…") if len(txt) > max_len else txt
    return ""


def build_mapping_manifest(
    *,
    template_columns: list[str],
    contacts_only: bool,
    randomize_external_ids: bool,
    external_id_digits: int,
    max_sellers: int,
    staging_df: pd.DataFrame,
) -> tuple[list[dict[str, str]], str]:
    """
    Build a template-driven mapping manifest (one row per template column).

    This is meant to be:
    - easy for humans to audit
    - easy for an AI to reason about without guessing
    """
    tmpl = [str(c) for c in template_columns]

    def ex(c: str) -> str:
        return _first_nonempty_example(staging_df, c)

    sellers_note = f"up to {max_sellers} seller people (template may cap Seller/Seller2/Seller3...)"
    prop_source = "contacts-derived" if contacts_only else "desired_outcome"

    known: dict[str, tuple[str, str]] = {
        "External Id": (
            "computed" if randomize_external_ids else prop_source,
            (
                f"Randomized digits-only id ({external_id_digits} digits) per output row."
                if randomize_external_ids
                else "Copied from input External Id when present (may be blank)."
            ),
        ),
        "Full Address": (prop_source, "One row per address (deduped)."),
        "Street": (prop_source, "From input Property Street (contacts-only derives from parsed address when possible)."),
        "City": (prop_source, "From input Property City (contacts-only derives from parsed address when possible)."),
        "State": (prop_source, "From input Property State (contacts-only derives from parsed address when possible)."),
        "Zip Code": (prop_source, "From input Property ZIP; fallback extracts ZIP from Full Address when missing."),
        "Status": ("constant/default", "Input Status if provided, else 'New'."),
        "Campaign": ("constant/default", "Input Campaign if provided, else 'Deal Machine'."),
        "Phase": ("constant/default", "Input Phase if provided, else 'Lead'."),
        "Tags": (
            "computed",
            "Preserves extra seller names as `extra_sellers:<names>` when more sellers exist than template slots.",
        ),
    }

    def seller_rule(kind: str) -> tuple[str, str]:
        if kind == "name":
            return ("contacts", f"Ranked contacts per address (Likely Owner first), {sellers_note}.")
        if kind == "email":
            return ("contacts", "From contacts email_address_1..3 (unique, preserved order).")
        if kind == "phone":
            return ("contacts", "From contacts phone_1..3 (normalized to digits-only, leading 1 removed).")
        return ("blank", "Left blank by default (no mapping rule).")

    rows: list[dict[str, str]] = []
    for col in tmpl:
        source = "blank"
        rule = "Left blank by default (no mapping rule)."
        if col in known:
            source, rule = known[col]
        elif col in {"Seller", "Seller2", "Seller3", "Seller4", "Seller5"}:
            source, rule = seller_rule("name")
        elif "Email" in col and col.startswith("Seller"):
            source, rule = seller_rule("email")
        elif "Phone" in col and col.startswith("Seller"):
            source, rule = seller_rule("phone")
        rows.append(_mapping_entry(column=col, source=source, rule=rule, example=ex(col)))

    md_lines: list[str] = []
    md_lines.append("## Template mapping manifest (Pete Properties Import)")
    md_lines.append("")
    md_lines.append("This is a template-driven mapping summary. Each row corresponds to a template column.")
    md_lines.append("")
    md_lines.append("| Template column | Source | Rule | Example (from output) |")
    md_lines.append("| --- | --- | --- | --- |")
    for r in rows:
        md_lines.append(
            "| "
            + " | ".join(
                [
                    str(r["template_column"]).replace("|", "\\|"),
                    str(r["source"]).replace("|", "\\|"),
                    str(r["rule"]).replace("|", "\\|"),
                    str(r["example"]).replace("|", "\\|"),
                ]
            )
            + " |"
        )
    md = "\n".join(md_lines).rstrip() + "\n"
    return rows, md


def normalize_email(email: Any) -> str:
    return _norm(email).strip().lower()


def sellers_from_contacts(contacts_df: pd.DataFrame) -> list[SellerContact]:
    """
    Convert contacts rows for a single address into ranked SellerContact(s).

    Ranking:
      1) Likely Owner first
      2) Has any phone/email
      3) Stable by contact_id (if present)
    """
    if contacts_df.empty:
        return []

    cols = set(contacts_df.columns)
    has_contact_id = "contact_id" in cols

    def build_row(row: pd.Series) -> SellerContact:
        first = _norm(row.get("first_name"))
        last = _norm(row.get("last_name"))
        name = " ".join([p for p in [first, last] if p]).strip()
        if not name:
            # sometimes name can be embedded in last_name or blank; fallback to contact_id
            name = coalesce(row.get("last_name"), row.get("contact_id"), "Unknown")

        emails = _unique_nonempty(
            [
                row.get("email_address_1"),
                row.get("email_address_2"),
                row.get("email_address_3"),
            ]
        )
        phones = _unique_phones([row.get("phone_1"), row.get("phone_2"), row.get("phone_3")])

        return SellerContact(
            name=name,
            emails=emails,
            phones=phones,
            is_likely_owner=_is_likely_owner(row.get("contact_flags")),
        )

    sellers: list[tuple[SellerContact, int]] = []
    for _, r in contacts_df.iterrows():
        sc = build_row(r)
        cid = 0
        if has_contact_id:
            try:
                cid = int(float(_norm(r.get("contact_id")) or 0))
            except ValueError:
                cid = 0
        sellers.append((sc, cid))

    # Deduplicate by normalized name (keep best ranked later; first pass ranks then uniq)
    def score(sc: SellerContact, cid: int) -> tuple[int, int, int]:
        # higher better
        has_contact = 1 if (sc.emails or sc.phones) else 0
        likely = 1 if sc.is_likely_owner else 0
        return (likely, has_contact, -cid)

    sellers.sort(key=lambda t: score(t[0], t[1]), reverse=True)

    unique: list[SellerContact] = []
    seen: set[str] = set()
    for sc, _cid in sellers:
        k = sc.name.strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        unique.append(sc)
    return unique


def sellers_from_desired_outcome(group_df: pd.DataFrame) -> list[SellerContact]:
    """
    Fallback if contacts join fails: derive up to N sellers from the desired-outcome rows.
    """
    if group_df.empty:
        return []

    def make(row: pd.Series) -> SellerContact:
        name = coalesce(row.get("Seller"), "Unknown")
        emails = _unique_nonempty([row.get("Seller Email"), row.get("Seller Email2"), row.get("Seller Email3")])
        phones = _unique_phones([row.get("Seller Phone"), row.get("Seller Phone2"), row.get("Seller Phone3")])
        return SellerContact(name=name, emails=emails, phones=phones, is_likely_owner=False)

    sellers: list[SellerContact] = []
    for _, r in group_df.iterrows():
        sellers.append(make(r))

    # uniq by name
    unique: list[SellerContact] = []
    seen: set[str] = set()
    for sc in sellers:
        k = sc.name.strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        unique.append(sc)
    return unique


def fill_seller_fields(row: dict[str, Any], who: str, sc: SellerContact, template_columns: set[str]) -> None:
    """
    Fill seller person + up to 5 emails/phones for this seller block, but only
    where the template has those columns.

    who:
      - "Seller"
      - "Seller2"
      - "Seller3"
      - (optionally) "Seller4", "Seller5" if present in the template
    """
    if who in template_columns:
        row[who] = sc.name

    # email columns differ for Seller vs Seller2+ (Seller uses "Seller Email", Seller2 uses "Seller2 Email")
    email_base = "Seller Email" if who == "Seller" else f"{who} Email"
    phone_base = "Seller Phone" if who == "Seller" else f"{who} Phone"

    # slot 1 uses base, slots 2-5 use suffix numbers
    email_cols = [
        email_base,
        f"{email_base}2",
        f"{email_base}3",
        f"{email_base}4",
        f"{email_base}5",
    ]
    phone_cols = [
        phone_base,
        f"{phone_base}2",
        f"{phone_base}3",
        f"{phone_base}4",
        f"{phone_base}5",
    ]

    for idx, col in enumerate(email_cols):
        if col in template_columns:
            row[col] = sc.emails[idx] if len(sc.emails) > idx else ""
    for idx, col in enumerate(phone_cols):
        if col in template_columns:
            row[col] = sc.phones[idx] if len(sc.phones) > idx else ""


def available_seller_people_slots(template_columns: set[str]) -> list[str]:
    """
    Determine how many distinct seller "people" columns exist in the template.
    Most DealMachine templates include Seller, Seller2, Seller3. Some may include more.
    """
    slots = []
    for who in ["Seller", "Seller2", "Seller3", "Seller4", "Seller5"]:
        if who in template_columns:
            slots.append(who)
    return slots


def build_address_report(
    desired_outcome_df: pd.DataFrame,
    contacts_df: pd.DataFrame,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """
    Report:
      - duplicates eliminated by address de-dupe
      - contacts per address
      - duplicate phone/email collisions per address (same phone/email used by >1 contact)
      - likely owner counts
    """
    report: dict[str, Any] = {}
    report["desired_outcome_rows"] = int(len(desired_outcome_df))
    report["desired_outcome_unique_addresses"] = int(desired_outcome_df["Full Address"].nunique(dropna=True))
    report["desired_outcome_duplicate_rows_eliminated"] = int(
        report["desired_outcome_rows"] - report["desired_outcome_unique_addresses"]
    )

    if "associated_property_address_full" not in contacts_df.columns:
        report["contacts_rows"] = int(len(contacts_df))
        report["contacts_parse_warning"] = "contacts file did not contain expected columns; collision report may be incomplete"
        return report, pd.DataFrame()

    c = contacts_df.copy()
    c["_addr_key"] = c["associated_property_address_full"].map(normalize_address_for_join)
    c["_phone_norm"] = c.get("phone_1", "").map(normalize_phone) if "phone_1" in c.columns else ""
    c["_email_norm"] = c.get("email_address_1", "").map(normalize_email) if "email_address_1" in c.columns else ""
    c["_likely_owner"] = c.get("contact_flags", "").map(_is_likely_owner) if "contact_flags" in c.columns else False

    rows: list[dict[str, Any]] = []
    for addr_key, g in c.groupby("_addr_key", dropna=False):
        if not _norm(addr_key):
            continue

        # phones: include phone_1/2/3 if present
        phone_cols = [col for col in ["phone_1", "phone_2", "phone_3"] if col in g.columns]
        phones = []
        for col in phone_cols:
            phones.extend([normalize_phone(x) for x in g[col].tolist()])
        phones = [p for p in phones if p]

        email_cols = [col for col in ["email_address_1", "email_address_2", "email_address_3"] if col in g.columns]
        emails = []
        for col in email_cols:
            emails.extend([normalize_email(x) for x in g[col].tolist()])
        emails = [e for e in emails if e]

        phone_counts: dict[str, int] = {}
        for p in phones:
            phone_counts[p] = phone_counts.get(p, 0) + 1
        email_counts: dict[str, int] = {}
        for e in emails:
            email_counts[e] = email_counts.get(e, 0) + 1

        dup_phones = sorted([p for p, n in phone_counts.items() if n > 1])
        dup_emails = sorted([e for e, n in email_counts.items() if n > 1])

        # estimate unique contact names
        names = []
        if "first_name" in g.columns or "last_name" in g.columns:
            for _, r in g.iterrows():
                nm = " ".join([_norm(r.get("first_name")), _norm(r.get("last_name"))]).strip()
                if nm:
                    names.append(nm.lower())
        unique_names = len(set(names)) if names else int(len(g))

        rows.append(
            {
                "addr_key": addr_key,
                "contacts_rows": int(len(g)),
                "unique_contact_names_est": int(unique_names),
                "likely_owner_contacts": int(g["_likely_owner"].sum()) if "_likely_owner" in g.columns else 0,
                "unique_phones": int(len(set(phones))),
                "duplicate_phones_count": int(len(dup_phones)),
                "duplicate_phones": "|".join(dup_phones),
                "unique_emails": int(len(set(emails))),
                "duplicate_emails_count": int(len(dup_emails)),
                "duplicate_emails": "|".join(dup_emails),
            }
        )

    addr_df = pd.DataFrame(rows).sort_values(
        by=["contacts_rows", "duplicate_phones_count", "duplicate_emails_count"], ascending=[False, False, False]
    )

    report["contacts_rows"] = int(len(c))
    report["contacts_unique_addresses"] = int(addr_df["addr_key"].nunique()) if not addr_df.empty else 0
    report["addresses_with_phone_collisions"] = int((addr_df["duplicate_phones_count"] > 0).sum()) if not addr_df.empty else 0
    report["addresses_with_email_collisions"] = int((addr_df["duplicate_emails_count"] > 0).sum()) if not addr_df.empty else 0

    return report, addr_df


def build_global_collision_reports(contacts_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Global collisions = same normalized phone/email appearing across multiple addresses.
    Returns: (phones_df, emails_df)
    """
    if "associated_property_address_full" not in contacts_df.columns:
        return pd.DataFrame(), pd.DataFrame()

    c = contacts_df.copy()
    c["_addr_key"] = c["associated_property_address_full"].map(normalize_address_for_join)

    # build long phone list across phone_1/2/3
    phone_cols = [col for col in ["phone_1", "phone_2", "phone_3"] if col in c.columns]
    phone_rows: list[dict[str, Any]] = []
    for col in phone_cols:
        tmp = c[["_addr_key", "first_name", "last_name", col]].copy()
        tmp = tmp.rename(columns={col: "phone"})
        for _, r in tmp.iterrows():
            p = normalize_phone(r.get("phone"))
            if not p:
                continue
            nm = " ".join([_norm(r.get("first_name")), _norm(r.get("last_name"))]).strip()
            phone_rows.append({"phone": p, "addr_key": r.get("_addr_key"), "name": nm})
    phones_long = pd.DataFrame(phone_rows)

    email_cols = [col for col in ["email_address_1", "email_address_2", "email_address_3"] if col in c.columns]
    email_rows: list[dict[str, Any]] = []
    for col in email_cols:
        tmp = c[["_addr_key", "first_name", "last_name", col]].copy()
        tmp = tmp.rename(columns={col: "email"})
        for _, r in tmp.iterrows():
            e = normalize_email(r.get("email"))
            if not e:
                continue
            nm = " ".join([_norm(r.get("first_name")), _norm(r.get("last_name"))]).strip()
            email_rows.append({"email": e, "addr_key": r.get("_addr_key"), "name": nm})
    emails_long = pd.DataFrame(email_rows)

    def summarize_long(df: pd.DataFrame, key_col: str) -> pd.DataFrame:
        if df.empty:
            # return empty with stable columns
            return pd.DataFrame(
                columns=[
                    key_col,
                    "address_count",
                    "occurrences",
                    "unique_names",
                    "addresses_sample",
                    "names_sample",
                ]
            )
        out = []
        for key, g in df.groupby(key_col):
            addrs = sorted(set([_norm(x) for x in g["addr_key"].tolist() if _norm(x)]))
            if len(addrs) <= 1:
                continue
            names = sorted(set([_norm(x) for x in g["name"].tolist() if _norm(x)]))
            out.append(
                {
                    key_col: key,
                    "address_count": len(addrs),
                    "occurrences": int(len(g)),
                    "unique_names": len(names),
                    "addresses_sample": "|".join(addrs[:10]),
                    "names_sample": "|".join(names[:10]),
                }
            )
        if not out:
            return pd.DataFrame(
                columns=[
                    key_col,
                    "address_count",
                    "occurrences",
                    "unique_names",
                    "addresses_sample",
                    "names_sample",
                ]
            )
        return pd.DataFrame(out).sort_values(by=["address_count", "occurrences"], ascending=[False, False])

    phones_df = summarize_long(phones_long, "phone")
    emails_df = summarize_long(emails_long, "email")
    return phones_df, emails_df


def build_seller_summary(
    desired_outcome_df: pd.DataFrame,
    contacts_df: pd.DataFrame,
    max_sellers: int = 5,
) -> pd.DataFrame:
    """
    A human-reviewable per-address rollup with seller names/emails/phones grouped.
    Uses the same seller ranking rule as staging (Likely Owner first).
    """
    contacts_by_key: dict[str, pd.DataFrame] = {}
    if "associated_property_address_full" in contacts_df.columns:
        c = contacts_df.copy()
        c["_addr_key"] = c["associated_property_address_full"].map(normalize_address_for_join)
        contacts_by_key = {k: v for k, v in c.groupby("_addr_key", dropna=False)}

    rows: list[dict[str, Any]] = []
    for full_addr, g in desired_outcome_df.groupby("Full Address", dropna=False):
        full_addr_str = _norm(full_addr)
        if not full_addr_str:
            continue

        addr_key = normalize_address_for_join(full_addr_str)
        contacts_group = contacts_by_key.get(addr_key, pd.DataFrame())

        sellers = sellers_from_contacts(contacts_group)
        if not sellers:
            sellers = sellers_from_desired_outcome(g)
        sellers = sellers[:max_sellers]

        # grouped values (unique)
        all_names = [sc.name for sc in sellers if sc.name]
        all_emails = _unique_nonempty([e for sc in sellers for e in sc.emails])
        all_phones = _unique_phones([p for sc in sellers for p in sc.phones])

        # extra stats when contacts are available
        likely_owner_contacts = 0
        contacts_rows = 0
        if not contacts_group.empty and "contact_flags" in contacts_group.columns:
            contacts_rows = int(len(contacts_group))
            likely_owner_contacts = int(contacts_group["contact_flags"].map(_is_likely_owner).sum())

        rows.append(
            {
                "Full Address": full_addr_str,
                "seller_count_selected": len(sellers),
                "seller_names_grouped": " | ".join(all_names),
                "seller_emails_grouped": " | ".join(all_emails),
                "seller_phones_grouped": " | ".join(all_phones),
                "contacts_rows_for_address": contacts_rows,
                "likely_owner_contacts_for_address": likely_owner_contacts,
            }
        )

    return pd.DataFrame(rows).sort_values(by=["seller_count_selected", "contacts_rows_for_address"], ascending=[False, False])


def default_desktop_downloads_dir() -> Path | None:
    """
    Prefer a 'Downloads' folder on the Desktop (as requested), otherwise fall back
    to the standard ~/Downloads folder.
    """
    home = Path.home()
    desktop_downloads = home / "Desktop" / "Downloads"
    if desktop_downloads.exists() and desktop_downloads.is_dir():
        return desktop_downloads
    downloads = home / "Downloads"
    if downloads.exists() and downloads.is_dir():
        return downloads
    return None


def maybe_copy_outputs_to_dir(paths: list[Path], dest_dir: Path | None) -> list[Path]:
    if dest_dir is None:
        return []
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for p in paths:
        if p.exists():
            dest = dest_dir / p.name
            shutil.copy2(p, dest)
            copied.append(dest)
    return copied


def ensure_dated_export_subfolder(
    base_dir: Path | None,
    prefix: str,
    date_format: str = "%m.%d.%y",
) -> Path | None:
    """
    Create (if needed) a dated subfolder inside base_dir, e.g.:
      fernando.dealmachine.clean.01.14.26
    If the folder already exists, add a numeric suffix to keep prior runs:
      fernando.dealmachine.clean.01.14.26-2
    """
    if base_dir is None:
        return None
    date_str = datetime.now().strftime(date_format)
    stem = f"{prefix}.{date_str}"
    candidate = base_dir / stem
    if not candidate.exists():
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    # keep history by suffixing
    i = 2
    while True:
        alt = base_dir / f"{stem}-{i}"
        if not alt.exists():
            alt.mkdir(parents=True, exist_ok=True)
            return alt
        i += 1


def build_export_basename(prefix: str, date_format: str = "%m.%d.%y") -> str:
    """
    Build a filename base like:
      PETE.DM.FERNANDO.CLEAN.01.14.26
    """
    date_str = datetime.now().strftime(date_format)
    return f"{prefix}.{date_str}"


def export_prefix_from_input_filename(filename: str) -> str:
    """
    Build a stable export prefix from an uploaded input filename.

    Example:
      "Lake City FL - Leads (1).csv" -> "lake-city-fl-leads.pete.clean"
    """
    stem = Path(filename).stem.strip()
    if not stem:
        return "export.pete.clean"

    # Lowercase slug: keep alnum, convert separators to hyphens.
    s = stem.lower()
    s = re.sub(r"[^\w\s-]+", " ", s)  # drop punctuation like "(1)" but keep contents as tokens
    s = re.sub(r"[_\s]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")

    # Drop purely numeric trailing token(s) (e.g., "-1" from copies).
    parts = [p for p in s.split("-") if p]
    while parts and re.fullmatch(r"\d+", parts[-1] or ""):
        parts.pop()

    # Keep it short: first 6 tokens is plenty for homelab import naming.
    parts = parts[:6] if parts else ["export"]
    base = "-".join(parts)
    return f"{base}.pete.clean"


def randomize_external_ids(
    df: pd.DataFrame,
    *,
    seed: int | None = None,
    digits: int = 10,
) -> pd.DataFrame:
    """
    Replace `External Id` with unique randomized numeric strings.
    Useful when the target system only imports a subset due to duplicate/blank IDs.
    """
    if "External Id" not in df.columns:
        return df
    if digits < 6:
        raise ValueError("digits must be >= 6 to reduce collision risk")

    rng = random.Random(seed)
    used: set[str] = set()

    def gen_one() -> str:
        low = 10 ** (digits - 1)
        high = (10**digits) - 1
        # retry until unique (N is small ~2k so this is fine)
        while True:
            v = str(rng.randint(low, high))
            if v not in used:
                used.add(v)
                return v

    out = df.copy()
    out["External Id"] = [gen_one() for _ in range(len(out))]
    return out


def _df_to_markdown_table(df: pd.DataFrame, columns: list[str], max_rows: int = 10) -> str:
    """
    Render a small markdown table without extra dependencies (no tabulate).
    """
    if df.empty:
        return "_(none)_"
    cols = [c for c in columns if c in df.columns]
    if not cols:
        return "_(none)_"
    view = df[cols].head(max_rows).copy()
    # stringify
    for c in cols:
        view[c] = view[c].map(lambda x: "" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x))
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] * len(cols)) + " |"
    rows = ["| " + " | ".join(view.iloc[i].tolist()) + " |" for i in range(len(view))]
    return "\n".join([header, sep, *rows])


def write_client_markdown_report(
    report_md_path: Path,
    *,
    desired_path: Path,
    contacts_path: Path,
    template_path: Path,
    out_xlsx_path: Path,
    out_csv_path: Path,
    seller_summary_csv_path: Path,
    report_summary: dict[str, Any],
    addr_report_df: pd.DataFrame,
    phones_global_df: pd.DataFrame,
    emails_global_df: pd.DataFrame,
    desktop_export_dir: Path | None,
    report_json_path: Path,
    addr_report_csv_path: Path,
    global_phones_csv_path: Path,
    global_emails_csv_path: Path,
) -> None:
    """
    Client-facing, factual summary describing what the run did and what it produced.
    """
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    desired_rows = int(report_summary.get("desired_outcome_rows", 0))
    desired_unique = int(report_summary.get("desired_outcome_unique_addresses", 0))
    deduped = int(report_summary.get("desired_outcome_duplicate_rows_eliminated", 0))
    contacts_rows = int(report_summary.get("contacts_rows", 0))

    md: list[str] = []
    md.append("## pete DEAL MACHEINE CLEAN REPORT")
    md.append("")
    md.append(f"- **Created**: {created_at}")
    md.append("")
    md.append("## Inputs used")
    md.append("")
    md.append(f"- **Desired-outcome CSV**: `{desired_path}`")
    md.append(f"- **Contacts CSV**: `{contacts_path}`")
    md.append(f"- **Properties template**: `{template_path}`")
    md.append("")
    md.append("## What this run did")
    md.append("")
    md.append("- **Deduped by address**: produced **one row per `Full Address`** in the import sheet.")
    md.append("- **Seller selection**: when multiple contacts exist for an address, contacts flagged **“Likely Owner”** are prioritized.")
    md.append("")
    md.append("## Key counts")
    md.append("")
    md.append(f"- **Desired-outcome rows (input)**: {desired_rows}")
    md.append(f"- **Unique addresses (input)**: {desired_unique}")
    md.append(f"- **Duplicate address rows eliminated**: {deduped}")
    md.append(f"- **Contacts rows (input)**: {contacts_rows}")
    md.append("")
    md.append("## Outputs produced")
    md.append("")
    md.append(f"- **Import workbook (upload this)**: `{out_xlsx_path}`")
    md.append("  - `Sheet1`: import-ready template-shaped sheet")
    md.append(f"- **Import CSV (optional)**: `{out_csv_path}` (same columns as `Sheet1`)")
    md.append(f"- **Seller summary CSV (review)**: `{seller_summary_csv_path}`")
    md.append(f"- **Summary JSON**: `{report_json_path}`")
    md.append(f"- **Per-address report CSV**: `{addr_report_csv_path}`")
    md.append(f"- **Global phone reuse CSV**: `{global_phones_csv_path}`")
    md.append(f"- **Global email reuse CSV**: `{global_emails_csv_path}`")
    if desktop_export_dir is not None:
        md.append(f"- **Copied to Downloads folder**: `{desktop_export_dir}`")
    md.append("")
    md.append("## Top items (for review)")
    md.append("")
    md.append("### Addresses with the most contacts / collisions (top 10)")
    md.append("")
    md.append(
        _df_to_markdown_table(
            addr_report_df,
            ["addr_key", "contacts_rows", "likely_owner_contacts", "duplicate_phones_count", "duplicate_emails_count"],
            max_rows=10,
        )
    )
    md.append("")
    md.append("### Phones reused across multiple addresses (top 10)")
    md.append("")
    md.append(_df_to_markdown_table(phones_global_df, ["phone", "address_count", "occurrences", "unique_names"], max_rows=10))
    md.append("")
    md.append("### Emails reused across multiple addresses (top 10)")
    md.append("")
    md.append(_df_to_markdown_table(emails_global_df, ["email", "address_count", "occurrences", "unique_names"], max_rows=10))
    md.append("")

    report_md_path.parent.mkdir(parents=True, exist_ok=True)
    report_md_path.write_text("\n".join(md).rstrip() + "\n", encoding="utf-8")


def build_staging(
    desired_outcome_df: pd.DataFrame,
    contacts_df: pd.DataFrame,
    template_columns: list[str],
    max_sellers: int = 5,
) -> pd.DataFrame:
    # Index contacts by normalized property address
    if "associated_property_address_full" in contacts_df.columns:
        contacts_df = contacts_df.copy()
        contacts_df["_addr_key"] = contacts_df["associated_property_address_full"].map(normalize_address_for_join)
    else:
        # If contacts file isn't usable, keep empty so we fall back to desired-outcome sellers
        contacts_df = pd.DataFrame(columns=["_addr_key"])

    contacts_by_addr: dict[str, pd.DataFrame] = {
        k: v for k, v in contacts_df.groupby("_addr_key", dropna=False)
    }

    template_col_set = set(template_columns)
    seller_people_slots = available_seller_people_slots(template_col_set)

    out_rows: list[dict[str, Any]] = []
    for full_addr, g in desired_outcome_df.groupby("Full Address", dropna=False):
        full_addr_str = _norm(full_addr)
        if not full_addr_str:
            continue

        base = g.iloc[0]

        row: dict[str, Any] = {c: "" for c in template_columns}

        # Property fields
        row["External Id"] = coalesce(base.get("External Id"))
        row["Full Address"] = full_addr_str

        # Template uses Street/City/State/Zip Code
        row["Street"] = coalesce(base.get("Property Street"))
        row["City"] = coalesce(base.get("Property City"))
        row["State"] = coalesce(base.get("Property State"))
        row["Zip Code"] = coalesce(base.get("Property ZIP"), extract_zip(full_addr_str))

        row["Status"] = coalesce(base.get("Status"), "New")
        row["Campaign"] = coalesce(base.get("Campaign"), "Deal Machine")
        row["Phase"] = coalesce(base.get("Phase"), "Lead")

        # Sellers
        addr_key = normalize_address_for_join(full_addr_str)
        sellers = sellers_from_contacts(contacts_by_addr.get(addr_key, pd.DataFrame()))
        if not sellers:
            sellers = sellers_from_desired_outcome(g)

        # Fill up to N sellers (people) where the template supports it
        sellers = sellers[: max_sellers]
        people_slots = seller_people_slots[: max_sellers]
        for idx, who in enumerate(people_slots):
            if idx >= len(sellers):
                break
            fill_seller_fields(row, who, sellers[idx], template_col_set)

        # If user asked for 5 but template only has 3 seller-person slots, keep extra seller names in Tags
        extra = sellers[len(people_slots) :]
        if extra and "Tags" in template_col_set:
            extra_names = ", ".join([sc.name for sc in extra if sc.name])
            if extra_names:
                current = _norm(row.get("Tags"))
                tag = f"extra_sellers:{extra_names}"
                row["Tags"] = f"{current},{tag}".strip(",") if current else tag

        out_rows.append(row)

    df = pd.DataFrame(out_rows, columns=template_columns)
    return df


@pete_template_generator(
    name="pete_properties_import",
    template_default=Path("uploads/templates/Properties Template (15).xlsx"),
    description="Generate Pete CRM Properties import file from DealMachine exports (dedupe to one row per address).",
)
def generate_pete_properties_import(
    *,
    desired_outcome_df: pd.DataFrame,
    contacts_df: pd.DataFrame,
    template_columns: list[str],
    max_sellers: int,
) -> pd.DataFrame:
    # Delegate to the existing implementation; decorator guarantees final shape/order.
    return build_staging(
        desired_outcome_df=desired_outcome_df,
        contacts_df=contacts_df,
        template_columns=template_columns,
        max_sellers=max_sellers,
    )


def run_build(
    *,
    uploads_dir: Path,
    inputs_dir: Path | None = None,
    outputs_dir: Path | None = None,
    desired_outcome: Path | None,
    contacts: Path | None,
    template: Path,
    export_prefix: str,
    export_date_format: str,
    out_xlsx: Path | None,
    out_csv: Path | None,
    seller_summary_csv: Path | None,
    max_sellers: int,
    randomize_external_ids_enabled: bool,
    external_id_seed: int | None,
    external_id_digits: int,
    report_json: Path,
    report_addresses_csv: Path,
    report_global_phones_csv: Path,
    report_global_emails_csv: Path,
    report_md: Path,
    desktop_copy: bool,
    desktop_copy_dir: Path | None,
    desktop_subfolder_prefix: str,
    desktop_subfolder_date_format: str,
    trace_calls: bool = False,
    trace_max_events: int = 50_000,
    trace_include_stdlib: bool = False,
    debug_report: bool = False,
    debug_sample_n: int = 25,
    status_match_warn_pct: float = 95.0,
    status_missing_seller_warn_count: int = 1,
    company_id: str | None = None,
    company_name: str | None = None,
    contacts_only: bool = False,
) -> BuildResult:
    """
    Programmatic entrypoint for building the DealMachine import workbook + reports.
    This is what the v0.02 CLI calls.
    """
    uploads_dir = Path(uploads_dir)
    base_inputs_dir = Path(inputs_dir) if inputs_dir is not None else uploads_dir
    base_outputs_dir = Path(outputs_dir) if outputs_dir is not None else uploads_dir

    desired_path: Path | None
    if contacts_only:
        desired_path = desired_outcome  # optional; may be None
    else:
        desired_path = desired_outcome if desired_outcome else _auto_pick_uploads_file(
            base_inputs_dir, must_contain="desired-outcome", suffix=".csv"
        )
    if contacts is not None:
        contacts_path = contacts
    else:
        if contacts_only:
            # Prefer a CSV that *looks* like a DealMachine contacts export by header.
            candidates = sorted(base_inputs_dir.glob("*.csv"))
            best = next((p for p in candidates if _csv_header_has_column(p, "associated_property_address_full")), None)
            contacts_path = best if best is not None else _auto_pick_uploads_file(
                base_inputs_dir, must_contain="contacts", suffix=".csv"
            )
        else:
            contacts_path = _auto_pick_uploads_file(base_inputs_dir, must_contain="contacts", suffix=".csv")
    template_path = Path(template)

    # Allow callers (UI/CLI) to opt into "use input name as export prefix"
    # without changing the run_build signature.
    if (not export_prefix) or str(export_prefix).strip().upper() == "AUTO_FROM_INPUT":
        src = desired_path if desired_path is not None else contacts_path
        export_prefix = export_prefix_from_input_filename(Path(src).name)

    export_base = build_export_basename(str(export_prefix), date_format=str(export_date_format))
    out_path = out_xlsx if out_xlsx else (base_outputs_dir / f"{export_base}.xlsx")
    out_csv_path = out_csv if out_csv else (base_outputs_dir / f"{export_base}.csv")
    seller_summary_csv_path = seller_summary_csv if seller_summary_csv else (base_outputs_dir / f"{export_base}.seller_summary.csv")

    tracker = RunTracker(
        runs_dir=(uploads_dir / "runs" / str(company_id)) if company_id else (uploads_dir / "runs"),
        app_version=APP_VERSION,
        inputs={
            "company_id": str(company_id) if company_id else "",
            "company_name": str(company_name) if company_name else "",
            "desired_outcome": str(desired_path) if desired_path else "",
            "contacts": str(contacts_path),
            "template": str(template_path),
        },
    )
    set_tracker(tracker)
    configure_logging(log_file=tracker.log_path)
    log = get_logger()
    log.info(
        "run_start run_id={} app_version={} desired_outcome={} contacts={} template={} contacts_only={}",
        tracker.run_id,
        APP_VERSION,
        str(desired_path) if desired_path else "",
        contacts_path,
        template_path,
        contacts_only,
    )
    if trace_calls:
        # project root = repo root (directory containing this file)
        tracker.start_call_trace(
            project_root=Path(__file__).resolve().parent,
            max_events=int(trace_max_events),
            include_stdlib=bool(trace_include_stdlib),
        )

    desired_df = None
    contacts_df = None
    template_columns = None
    staging_df = None
    addr_report_df = None
    phones_global_df = None
    emails_global_df = None
    report = {}

    try:
        if desired_path is not None:
            with tracker.step("load_desired") as st:
                desired_df = load_csv(desired_path)
                st.metric(rows=len(desired_df), cols=len(desired_df.columns))
        else:
            # contacts-only mode: derive desired_df from contacts after contacts load
            with tracker.step("load_desired") as st:
                st.status = "warn"
                st.metric(rows=0, cols=0, note="contacts_only: derived from contacts")

        with tracker.step("load_contacts") as st:
            contacts_df = load_csv(contacts_path)
            st.metric(rows=len(contacts_df), cols=len(contacts_df.columns))

        if desired_df is None:
            with tracker.step("derive_properties_from_contacts") as st:
                desired_df = build_desired_from_contacts(contacts_df)
                st.metric(rows=len(desired_df), cols=len(desired_df.columns))

        with tracker.step("load_template") as st:
            template_df = pd.read_excel(template_path, nrows=0)
            template_columns = template_df.columns.tolist()
            st.metric(cols=len(template_columns))

        with tracker.step("build_staging") as st:
            staging_df = generate_pete_properties_import(
                desired_outcome_df=desired_df,
                contacts_df=contacts_df,
                max_sellers=max_sellers,
                template_path=template_path,
            )
            st.metric(rows=len(staging_df))
            tracker.set_summary(
                generator="pete_properties_import",
                template_path=str(template_path),
                generator_settings={
                    "max_sellers": int(max_sellers),
                    "contacts_only": bool(contacts_only),
                    "randomize_external_ids": bool(randomize_external_ids_enabled),
                    "external_id_seed": int(external_id_seed) if external_id_seed is not None else None,
                    "external_id_digits": int(external_id_digits),
                },
            )

        if randomize_external_ids_enabled:
            staging_df = randomize_external_ids(
                staging_df,
                seed=external_id_seed,
                digits=int(external_id_digits),
            )

        summary_df = build_seller_summary(desired_df, contacts_df, max_sellers=max_sellers)
        if not summary_df.empty and "External Id" in staging_df.columns and "Full Address" in staging_df.columns:
            summary_df = summary_df.merge(
                staging_df[["Full Address", "External Id"]],
                on="Full Address",
                how="left",
            )

        with tracker.step("write_outputs") as st:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            # Keep phone columns stable (digits-only strings) in both XLSX + CSV.
            staging_df = normalize_phone_columns(staging_df)
            # Avoid commas/newlines in cells for safer imports.
            staging_df = sanitize_for_import(staging_df)
            with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
                staging_df.to_excel(writer, sheet_name="Sheet1", index=False)

            out_csv_path.parent.mkdir(parents=True, exist_ok=True)
            staging_df.to_csv(out_csv_path, index=False)

            if not summary_df.empty:
                seller_summary_csv_path.parent.mkdir(parents=True, exist_ok=True)
                summary_df.to_csv(seller_summary_csv_path, index=False)

            st.metric(xlsx=str(out_path.name), csv=str(out_csv_path.name))

        with tracker.step("write_reports") as st:
            report, addr_report_df = build_address_report(desired_df, contacts_df)
            report_json.parent.mkdir(parents=True, exist_ok=True)
            report_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

            if not addr_report_df.empty:
                report_addresses_csv.parent.mkdir(parents=True, exist_ok=True)
                addr_report_df.to_csv(report_addresses_csv, index=False)

            phones_global_df, emails_global_df = build_global_collision_reports(contacts_df)
            if not phones_global_df.empty:
                report_global_phones_csv.parent.mkdir(parents=True, exist_ok=True)
                phones_global_df.to_csv(report_global_phones_csv, index=False)
            if not emails_global_df.empty:
                report_global_emails_csv.parent.mkdir(parents=True, exist_ok=True)
                emails_global_df.to_csv(report_global_emails_csv, index=False)

            st.metric(report_json=str(report_json.name))

        # Desktop copy destination
        desktop_dir = desktop_copy_dir if desktop_copy_dir else default_desktop_downloads_dir()
        desktop_export_dir = ensure_dated_export_subfolder(
            desktop_dir,
            prefix=str(desktop_subfolder_prefix),
            date_format=str(desktop_subfolder_date_format),
        )

        write_client_markdown_report(
            report_md,
            desired_path=desired_path,
            contacts_path=contacts_path,
            template_path=template_path,
            out_xlsx_path=out_path,
            out_csv_path=out_csv_path,
            seller_summary_csv_path=seller_summary_csv_path,
            report_summary=report,
            addr_report_df=addr_report_df,
            phones_global_df=phones_global_df,
            emails_global_df=emails_global_df,
            desktop_export_dir=desktop_export_dir if desktop_copy else None,
            report_json_path=report_json,
            addr_report_csv_path=report_addresses_csv,
            global_phones_csv_path=report_global_phones_csv,
            global_emails_csv_path=report_global_emails_csv,
        )

        copied_paths: list[Path] = []
        if desktop_copy:
            copied_paths = maybe_copy_outputs_to_dir(
                [
                    out_path,
                    out_csv_path,
                    seller_summary_csv_path,
                    report_json,
                    report_addresses_csv,
                    report_global_phones_csv,
                    report_global_emails_csv,
                    report_md,
                ],
                desktop_export_dir,
            )

        staging_rows = int(len(staging_df))
        unique_addresses = int(staging_df["Full Address"].nunique()) if "Full Address" in staging_df.columns else staging_rows

        # Runtime summary + Acki diagram from this run
        tracker.set_summary(
            staging_rows=staging_rows,
            staging_unique_addresses=unique_addresses,
            desired_outcome_duplicate_rows_eliminated=int(report.get("desired_outcome_duplicate_rows_eliminated", 0)),
        )
        tracker.set_output("out_xlsx", out_path)
        tracker.set_output("out_csv", out_csv_path)
        tracker.set_output("seller_summary_csv", seller_summary_csv_path)
        tracker.set_output("report_md", report_md)

        # Template mapping manifest (one row per template column)
        try:
            manifest_rows, manifest_md = build_mapping_manifest(
                template_columns=[str(c) for c in (template_columns or [])],
                contacts_only=bool(contacts_only),
                randomize_external_ids=bool(randomize_external_ids_enabled),
                external_id_digits=int(external_id_digits),
                max_sellers=int(max_sellers),
                staging_df=staging_df,
            )
            mapping_md_path = tracker.runs_dir / f"{tracker.run_id}.mapping.md"
            mapping_json_path = tracker.runs_dir / f"{tracker.run_id}.mapping.json"
            mapping_md_path.write_text(manifest_md, encoding="utf-8")
            mapping_json_path.write_text(json.dumps(manifest_rows, indent=2), encoding="utf-8")
            tracker.set_output("mapping_md", mapping_md_path)
            tracker.set_output("mapping_json", mapping_json_path)
        except Exception:  # noqa: BLE001 - best-effort mapping manifest; never fail the run
            pass

        return_value = BuildResult(
            out_xlsx=out_path,
            out_csv=out_csv_path,
            seller_summary_csv=seller_summary_csv_path,
            report_json=report_json,
            report_addresses_csv=report_addresses_csv,
            report_global_phones_csv=report_global_phones_csv,
            report_global_emails_csv=report_global_emails_csv,
            report_md=report_md,
            desktop_export_dir=desktop_export_dir if desktop_copy else None,
            copied_paths=copied_paths,
            staging_rows=staging_rows,
            staging_unique_addresses=unique_addresses,
        )
        return return_value
    except Exception:
        log.exception("run_failed run_id={}", tracker.run_id)
        raise
    finally:
        # Optional deep-dive debug report (separate from the normal summary)
        # This keeps the regular summary useful and stable, while allowing a richer
        # report to be generated only when requested (or on failure).
        debug_metrics: dict[str, Any] | None = None
        try:
            if debug_report:
                metrics = compute_debug_metrics(
                    desired_df=desired_df,
                    contacts_df=contacts_df,
                    staging_df=staging_df,
                    addr_report_df=addr_report_df,
                    phones_global_df=phones_global_df,
                    emails_global_df=emails_global_df,
                    sample_n=int(debug_sample_n),
                )
                debug_metrics = metrics
                write_debug_report(
                    debug_json_path=tracker.debug_json_path,
                    debug_md_path=tracker.debug_md_path,
                    run_id=tracker.run_id,
                    metrics=metrics,
                )
                tracker.set_output("debug_md", tracker.debug_md_path)
                tracker.set_output("debug_json", tracker.debug_json_path)
        except Exception:  # noqa: BLE001 - best-effort debug report; never fail the run on diagnostics
            pass

        # Default end status rules (best-effort, high-signal)
        # - FAIL if any runtime step failed
        # - WARN if match rate is low or many sellers missing
        # - OK otherwise
        try:
            overall_status = "OK"
            reasons: list[str] = []
            for s in tracker.to_dict().get("steps", []):
                if s.get("status") == "fail":
                    overall_status = "FAIL"
                    reasons.append(f"step_failed:{s.get('name')}")
            if overall_status != "FAIL" and debug_metrics is not None:
                match = debug_metrics.get("address_match_rate") or {}
                pct = match.get("pct")
                try:
                    pct_val = float(pct)
                except Exception:  # noqa: BLE001 - best-effort parsing of pct from debug metrics
                    pct_val = None
                missing = int(debug_metrics.get("addresses_missing_seller_count", 0) or 0)
                if pct_val is not None and pct_val < float(status_match_warn_pct):
                    overall_status = "WARN"
                    reasons.append(f"match_pct<{status_match_warn_pct}: {pct_val}")
                if missing >= int(status_missing_seller_warn_count) and int(status_missing_seller_warn_count) > 0:
                    overall_status = "WARN"
                    reasons.append(f"missing_seller_count={missing}")
            tracker.set_summary(overall_status=overall_status, overall_reasons=reasons)
        except Exception:  # noqa: BLE001 - best-effort status computation; never fail the run on diagnostics
            pass
        # Always attempt to flush trace + run record even if interrupted.
        try:
            tracker.stop_call_trace()
        except Exception:  # noqa: BLE001 - best-effort stop trace; never fail the run on diagnostics
            pass
        try:
            tracker.write()
        except Exception:  # noqa: BLE001 - best-effort write run record; never fail the run on diagnostics
            pass
        try:
            # Generate Acki-style diagram (.flow.txt + .summary.md) into uploads/flowcharts/
            flow_dir = default_flowcharts_dir(uploads_dir, company_id=str(company_id) if company_id else None)
            flow_dir.mkdir(parents=True, exist_ok=True)
            acki_name = f"acki_run_{tracker.run_id}"
            (flow_dir / f"{acki_name}.flow.txt").write_text(generate_acki_flow_from_run(tracker.to_dict()), encoding="utf-8")
            (flow_dir / f"{acki_name}.summary.md").write_text(tracker.to_markdown(), encoding="utf-8")

            # Deep diagram only when debug metrics are available (v0.0.4)
            if debug_metrics is not None:
                (flow_dir / f"{acki_name}.deep.flow.txt").write_text(
                    generate_acki_deep_flow(tracker.to_dict(), debug_metrics),
                    encoding="utf-8",
                )
                (flow_dir / f"{acki_name}.deep.summary.md").write_text(
                    tracker.to_markdown(),
                    encoding="utf-8",
                )
        except Exception:  # noqa: BLE001 - best-effort diagram generation; never fail the run on diagnostics
            pass

    # (unreachable; return occurs in try)


def _auto_pick_uploads_file(data_dir: Path, must_contain: str, suffix: str) -> Path:
    candidates = sorted(data_dir.glob(f"*{suffix}"))
    for p in candidates:
        if must_contain.lower() in p.name.lower():
            return p
    if candidates:
        return candidates[0]
    raise FileNotFoundError(f"No {suffix} files found in {data_dir}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build template-shaped staging XLSX deduped to one row per address.")
    ap.add_argument("--uploads-dir", default="uploads", help="Directory containing inputs (default: uploads)")
    ap.add_argument("--desired-outcome", default=None, help="Path to desired-outcome CSV (default: auto-detect in uploads)")
    ap.add_argument("--contacts", default=None, help="Path to DealMachine contacts CSV (default: auto-detect in uploads)")
    ap.add_argument("--template", default="uploads/templates/Properties Template (15).xlsx", help="Path to template XLSX")
    ap.add_argument("--export-prefix", default="PETE.DM.FERNANDO.CLEAN", help="Base filename prefix for exports")
    ap.add_argument(
        "--export-date-format",
        default="%m.%d.%y",
        help="Date format used in export filenames (default: %m.%d.%y -> 01.14.26)",
    )
    ap.add_argument("--out", default=None, help="Output XLSX path (default: uploads/<prefix>.<date>.xlsx)")
    ap.add_argument("--out-csv", default=None, help="Output CSV path (default: uploads/<prefix>.<date>.csv)")
    ap.add_argument("--max-sellers", type=int, default=5, help="Max sellers/contacts to include (default 5)")
    ap.add_argument(
        "--randomize-external-ids",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Replace External Id with unique randomized IDs for each output row (default: false).",
    )
    ap.add_argument(
        "--external-id-seed",
        type=int,
        default=None,
        help="Optional seed for --randomize-external-ids (makes IDs repeatable).",
    )
    ap.add_argument(
        "--external-id-digits",
        type=int,
        default=10,
        help="Digits for randomized External Ids (default: 10).",
    )
    ap.add_argument("--report-json", default="uploads/staging_report.json", help="Where to write JSON summary report")
    ap.add_argument(
        "--report-addresses-csv",
        default="uploads/staging_report_addresses.csv",
        help="Where to write per-address collision report CSV",
    )
    ap.add_argument(
        "--report-global-phones-csv",
        default="uploads/staging_report_global_phones.csv",
        help="Where to write global phone reuse report CSV (phones reused across multiple addresses)",
    )
    ap.add_argument(
        "--report-global-emails-csv",
        default="uploads/staging_report_global_emails.csv",
        help="Where to write global email reuse report CSV (emails reused across multiple addresses)",
    )
    ap.add_argument(
        "--report-md",
        default="uploads/staging_report.md",
        help="Where to write a client-facing markdown report describing this run",
    )
    ap.add_argument(
        "--seller-summary-csv",
        default=None,
        help="Seller summary CSV output path (default: uploads/<prefix>.<date>.seller_summary.csv)",
    )
    ap.add_argument(
        "--desktop-copy",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Also copy the generated XLSX + report files into Desktop/Downloads (or ~/Downloads). Default: true.",
    )
    ap.add_argument(
        "--desktop-copy-dir",
        default=None,
        help="Override the directory used for --desktop-copy (e.g. /Users/you/Desktop/Downloads)",
    )
    ap.add_argument(
        "--desktop-subfolder-prefix",
        default="fernando.dealmachine.clean",
        help="When copying to Downloads, create a dated subfolder with this prefix (default: fernando.dealmachine.clean).",
    )
    ap.add_argument(
        "--desktop-subfolder-date-format",
        default="%m.%d.%y",
        help="Date format used in the subfolder name (default: %m.%d.%y -> 01.14.26).",
    )
    args = ap.parse_args()

    result = run_build(
        uploads_dir=Path(args.uploads_dir),
        desired_outcome=Path(args.desired_outcome) if args.desired_outcome else None,
        contacts=Path(args.contacts) if args.contacts else None,
        template=Path(args.template),
        export_prefix=str(args.export_prefix),
        export_date_format=str(args.export_date_format),
        out_xlsx=Path(args.out) if args.out else None,
        out_csv=Path(args.out_csv) if args.out_csv else None,
        seller_summary_csv=Path(args.seller_summary_csv) if args.seller_summary_csv else None,
        max_sellers=int(args.max_sellers),
        randomize_external_ids_enabled=bool(args.randomize_external_ids),
        external_id_seed=args.external_id_seed,
        external_id_digits=int(args.external_id_digits),
        report_json=Path(args.report_json),
        report_addresses_csv=Path(args.report_addresses_csv),
        report_global_phones_csv=Path(args.report_global_phones_csv),
        report_global_emails_csv=Path(args.report_global_emails_csv),
        report_md=Path(args.report_md),
        desktop_copy=bool(args.desktop_copy),
        desktop_copy_dir=Path(args.desktop_copy_dir).expanduser() if args.desktop_copy_dir else None,
        desktop_subfolder_prefix=str(args.desktop_subfolder_prefix),
        desktop_subfolder_date_format=str(args.desktop_subfolder_date_format),
    )

    print(f"Wrote: {result.out_xlsx}")
    print(f"Wrote: {result.out_csv}")
    if result.seller_summary_csv.exists():
        print(f"Wrote: {result.seller_summary_csv}")
    print("rows:", result.staging_rows, "unique addresses:", result.staging_unique_addresses)
    print(f"Report: {result.report_json}")
    if result.report_addresses_csv.exists():
        print(f"Address report CSV: {result.report_addresses_csv}")
    if result.report_global_phones_csv.exists():
        print(f"Global phones report CSV: {result.report_global_phones_csv}")
    if result.report_global_emails_csv.exists():
        print(f"Global emails report CSV: {result.report_global_emails_csv}")
    if result.report_md.exists():
        print(f"Markdown report: {result.report_md}")
    if result.copied_paths and result.desktop_export_dir:
        print(f"Also copied to folder: {result.desktop_export_dir}")
        for p in result.copied_paths:
            print(f"  - {p}")


if __name__ == "__main__":
    main()

