from __future__ import annotations

import pandas as pd


def test_strip_zip_from_full_address_removes_trailing_zip() -> None:
    from build_staging import strip_zip_from_full_address

    df = pd.DataFrame(
        [
            {"Full Address": "101 Ne Omar Ter Lake City Fl 32055", "Zip Code": "32055"},
            {"Full Address": "101 Ne Omar Ter, Lake City, FL 32055-1234", "Zip Code": "32055"},
        ]
    )
    out = strip_zip_from_full_address(df)
    assert out.loc[0, "Full Address"].endswith("32055") is False
    assert out.loc[0, "Full Address"] == "101 Ne Omar Ter Lake City Fl"
    assert out.loc[1, "Full Address"] == "101 Ne Omar Ter, Lake City, FL"

