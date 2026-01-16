from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd


def _looks_like_embedded_csv_single_column(df: pd.DataFrame) -> bool:
    """
    DealMachine contacts export sometimes arrives as a CSV where each entire row is
    stored as ONE quoted cell (so pandas sees a single column whose header contains
    all the real column names separated by commas).
    """
    if df.shape[1] != 1:
        return False
    header = str(df.columns[0])
    # Heuristic: header contains many commas + expected first fields
    return header.startswith("contact_id,associated_property_address_full,") and header.count(",") > 10


def _parse_embedded_csv_file(path: Path) -> pd.DataFrame:
    """
    Parse a "CSV inside a single quoted column" file into a normal DataFrame.

    Example first line in file:
      "contact_id,associated_property_address_full,first_name,..."
    Example data line in file:
      "1504,""5801 E 9th St, Kansas City, Mo 64125"",Mark,Morales,..."
    """
    # Read raw lines (utf-8-sig handles BOMs)
    raw_lines = path.read_text(encoding="utf-8-sig").splitlines()
    if not raw_lines:
        return pd.DataFrame()

    def normalize_embedded(line: str) -> str:
        s = line.strip()
        # strip outer quotes if present
        if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
            s = s[1:-1]
        # unescape doubled quotes (CSV escaping)
        s = s.replace('""', '"')
        return s

    header_line = normalize_embedded(raw_lines[0])
    header = next(csv.reader([header_line], delimiter=",", quotechar='"', doublequote=True))

    rows: list[list[str]] = []
    for line in raw_lines[1:]:
        if not line.strip():
            continue
        row_line = normalize_embedded(line)
        row = next(csv.reader([row_line], delimiter=",", quotechar='"', doublequote=True))
        rows.append(row)

    df = pd.DataFrame(rows, columns=header)
    return df


def load_csv(path: Path) -> pd.DataFrame:
    """Load vendor CSV with explicit comma parsing."""
    df = pd.read_csv(
        path,
        sep=",",
        engine="python",
        skipinitialspace=True,
        quotechar='"',
        encoding="utf-8-sig"
    )
    if _looks_like_embedded_csv_single_column(df):
        return _parse_embedded_csv_file(path)
    return df


def load_excel(path: Path) -> pd.DataFrame:
    """Load an Excel file into a DataFrame."""
    return pd.read_excel(path)
