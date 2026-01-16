from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd


def load_template_columns(template_path: Path) -> list[str]:
    """
    Load template columns (header row) from a Pete CRM import template XLSX.
    """
    df = pd.read_excel(Path(template_path), nrows=0)
    return [str(c) for c in df.columns.tolist()]


def ensure_template_shape(df: pd.DataFrame, template_columns: Iterable[str], *, drop_extra: bool = True) -> pd.DataFrame:
    """
    Ensure the dataframe matches the template schema:
    - add missing columns (empty string)
    - order columns to match template
    - optionally drop extra columns
    """
    cols = [str(c) for c in template_columns]
    out = df.copy()
    for c in cols:
        if c not in out.columns:
            out[c] = ""
    if drop_extra:
        out = out[cols]
    else:
        # Put template columns first, preserve any extras after.
        extras = [c for c in out.columns if c not in cols]
        out = out[cols + extras]
    return out

