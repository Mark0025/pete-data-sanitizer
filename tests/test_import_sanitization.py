from __future__ import annotations

import pandas as pd


def test_sanitize_for_import_removes_commas_and_newlines() -> None:
    from build_staging import sanitize_for_import

    df = pd.DataFrame(
        [
            {
                "Full Address": "123 Main St, Lake City, FL 32055",
                "Seller": "Doe, John",
                "Notes": "line1\nline2",
                "Empty": None,
            }
        ]
    )
    out = sanitize_for_import(df)

    assert "," not in out.loc[0, "Full Address"]
    assert "," not in out.loc[0, "Seller"]
    assert "\n" not in out.loc[0, "Notes"]
    assert out.loc[0, "Empty"] == ""

