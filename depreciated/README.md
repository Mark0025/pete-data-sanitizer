## Deprecated documentation

This file is the previous top-level `README.md` preserved for reference.

If you are looking for the current documentation, see the root `README.md`.

---

## What this app does (current behavior)

This project turns DealMachine exports into a **single, import-ready Properties workbook** that has:

- **One row per property address** (no duplicate addresses)
- Seller contact details filled into the DealMachine Properties template columns
- Extra review/report files that show where duplicates and data collisions exist

The current main entrypoint is `build_staging.py`.

## Why this exists

The DealMachine data you provided comes in two shapes:

- **Desired outcome CSV** (property + seller rows):
  - Path example: `uploads/Desired-outcome....csv`
  - Contains many duplicate addresses because it can include **multiple seller rows per address**
- **Contacts CSV** (people/contact records per property address):
  - Path example: `uploads/dealmachine-contacts-....csv`
  - One address can have multiple contacts, with phones/emails and flags like **“Likely Owner”**

petes Properties template (`uploads/templates/Properties Template (15).xlsx`) is shaped like:

- **One property per row**
- Up to **three seller “people”**: `Seller`, `Seller2`, `Seller3`
- Up to **five emails and five phones per seller** (where those columns exist):
  - Seller: `Seller Email … Seller Email5`, `Seller Phone … Seller Phone5`
  - Seller2: `Seller2 Email … Seller2 Email5`, `Seller2 Phone … Seller2 Phone5`
  - Seller3: `Seller3 Email … Seller3 Email5`, `Seller3 Phone … Seller3 Phone5`

Because the template is “one property per row”, we must **dedupe the desired outcome file** by address and then choose the best seller contacts to fill into the seller fields.

## Inputs

By default, `build_staging.py` looks in `uploads/` and auto-detects:

- A CSV whose filename contains `desired-outcome`
- A CSV whose filename contains `contacts`

You can also pass paths explicitly via CLI flags.

## Outputs

Running the generator produces:

- **`uploads/staging.xlsx`** (this is the file you upload/import)
  - `Sheet1`: Import-ready template-shaped sheet
  - `SellerSummary`: Human-review sheet with grouped seller names/emails/phones per address

Reports (for analysis only; do not upload these):

- `uploads/staging_report.json`: summary counts (rows, unique addresses, duplicates eliminated, etc.)
- `uploads/staging_report_addresses.csv`: per-address stats including:
  - number of contacts at the address
  - “Likely Owner” counts
  - duplicate phone/email collisions within the address
- `uploads/staging_report_global_phones.csv`: phones reused across multiple different addresses
- `uploads/staging_report_global_emails.csv`: emails reused across multiple different addresses

In addition, the script copies the outputs into a dated folder inside Downloads:

- `~/Desktop/Downloads/fernando.dealmachine.clean.MM.DD.YY/` (preferred)
- or `~/Downloads/fernando.dealmachine.clean.MM.DD.YY/` (fallback)

If a folder for that date already exists, it writes `...-2`, `...-3`, etc.

## How seller selection works

When multiple contacts exist for a single property address, the script ranks them to choose the best sellers:

1. Contacts whose `contact_flags` contains **“Likely Owner”** come first
2. Contacts that have **any phone or email** come next
3. Stable ordering tie-break (by `contact_id` when available)

It then fills seller “people” into the available template slots:

- `Seller`, `Seller2`, `Seller3` (and `Seller4`, `Seller5` only if the template actually contains those columns)

If more seller contacts exist than the template has seller-person slots, the extra seller names are preserved in the `Tags` column as:

- `extra_sellers:<comma separated names>`

## DealMachine contacts CSV parsing (important)

The contacts export you provided was formatted as a **CSV where each row is stored as a single quoted string** (so pandas initially reads it as one column).

`loaders.py` includes a special parser that detects this “single-column embedded CSV” shape and converts it into a normal DataFrame with real columns like:

- `associated_property_address_full`
- `first_name`, `last_name`
- `contact_flags`
- `email_address_1..3`
- `phone_1..3`

## How to run

From the project directory:

```bash
uv run python build_staging.py
```

Common options:

- Write output somewhere else:

```bash
uv run python build_staging.py --out uploads/staging.xlsx
```

- Override inputs explicitly:

```bash
uv run python build_staging.py \
  --desired-outcome "uploads/Desired-outcome....csv" \
  --contacts "uploads/dealmachine-contacts....csv" \
  --template "uploads/templates/Properties Template (15).xlsx" \
  --out "uploads/staging.xlsx"
```

- Disable the Downloads copy:

```bash
uv run python build_staging.py --no-desktop-copy
```

## What the “app” is right now

This repository is currently a **data transformation utility**, not a web app:

- `build_staging.py`: main generator that produces the import workbook + reports
- `loaders.py`: CSV/XLSX loader helpers, including special parsing for the contacts export format
- `inspect_data.py`: small helpers used for inspection (summaries/null counts)
- `main.py`: an earlier inspection script (not the primary workflow now)

## CLI (v0.02)

This project now includes a small CLI module (based on the plan in `DEV_MAN/Plans/Pyflowv1.md`):

- **Purpose**: a clean, expandable command interface for running the pipeline
- **Style**: supports both subcommands and a simple **numbered menu**

### Run the CLI

If dependencies are installed via UV, you can run:

```bash
uv run pete-dm-clean --help
```

### Build exports (recommended)

```bash
uv run pete-dm-clean build
```

Common options:

- Randomize External IDs (helps when imports fail due to duplicate/blank IDs):

```bash
uv run pete-dm-clean build --randomize-external-ids
```

### Interactive menu

```bash
uv run pete-dm-clean menu
```

This uses `questionary` if installed; otherwise it falls back to a simple numeric prompt.

