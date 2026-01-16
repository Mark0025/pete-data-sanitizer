from pathlib import Path

from loaders import load_csv, load_excel
from inspect_data import summarize, null_report, owner_counts


DATA_DIR = Path("uploads")

# Locate files
csv_path = next(DATA_DIR.glob("*.csv"))
xlsx_path = next(DATA_DIR.glob("*.xlsx"))

# Load data
csv_df = load_csv(csv_path)
template_df = load_excel(xlsx_path)

# ---- CSV INSPECTION ----
print("\n=== CSV SUMMARY ===")
print(summarize(csv_df))

print("\n=== CSV NULL REPORT (top 10) ===")
print(null_report(csv_df).head(10))

print("\n=== CSV SAMPLE ROWS ===")
print(csv_df.head(5))

# 🔴 UPDATE THIS AFTER YOU CONFIRM COLUMN NAME
PROPERTY_COLUMN = "Property Address"

if PROPERTY_COLUMN in csv_df.columns:
    print("\n=== OWNERS PER PROPERTY (top 10) ===")
    counts = owner_counts(csv_df, PROPERTY_COLUMN)
    print(counts.head(10))
    print("\nMAX OWNERS FOR ANY PROPERTY:", counts.max())
else:
    print(
        f"\n⚠️ Property column '{PROPERTY_COLUMN}' not found.\n"
        f"Available columns:\n{csv_df.columns.tolist()}"
    )

# ---- TEMPLATE INSPECTION ----
print("\n=== TEMPLATE SUMMARY ===")
print(summarize(template_df))

print("\n=== TEMPLATE COLUMNS ===")
print(template_df.columns.tolist())
