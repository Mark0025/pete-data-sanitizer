import pandas as pd


def summarize(df: pd.DataFrame) -> dict:
    """Basic structural summary of a DataFrame."""
    return {
        "rows": df.shape[0],
        "columns": df.shape[1],
        "column_names": df.columns.tolist(),
    }


def null_report(df: pd.DataFrame) -> pd.Series:
    """Count nulls per column."""
    return df.isna().sum().sort_values(ascending=False)


def owner_counts(df: pd.DataFrame, property_col: str) -> pd.Series:
    """
    Count how many rows (owners) exist per property.
    This reveals multi-owner properties.
    """
    return (
        df.groupby(property_col)
        .size()
        .sort_values(ascending=False)
    )
