from __future__ import annotations

import pandas as pd

from pete_dm_clean.template_inherit import ensure_template_shape


def test_ensure_template_shape_orders_and_fills_missing():
    template_cols = ["A", "B", "C"]
    df = pd.DataFrame([{"B": "b1", "A": "a1"}])

    out = ensure_template_shape(df, template_cols, drop_extra=True)
    assert list(out.columns) == template_cols
    assert out.loc[0, "A"] == "a1"
    assert out.loc[0, "B"] == "b1"
    assert out.loc[0, "C"] == ""


def test_ensure_template_shape_drops_extras_by_default():
    template_cols = ["A"]
    df = pd.DataFrame([{"A": "a", "EXTRA": "x"}])
    out = ensure_template_shape(df, template_cols, drop_extra=True)
    assert list(out.columns) == ["A"]
    assert out.loc[0, "A"] == "a"

