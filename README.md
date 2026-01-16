## pete dealmachine cleaner (v0.02)

This project is a small data-cleaning utility that takes DealMachine exports and produces **Pete Properties Import-ready files** (XLSX + CSV) with **one row per address** and seller contacts filled in.

The output schema is driven by the Excel template in `uploads/templates/` (default: `Properties Template (15).xlsx`).

### What you upload to DealMachine

- Upload the **XLSX** that is generated (example): `uploads/PETE.DM.FERNANDO.CLEAN.01.14.26.xlsx`
  - It contains a `Sheet1` tab that matches the template format.

### What the app generates

- **Import XLSX**: `uploads/<PREFIX>.<DATE>.xlsx`
- **Import CSV (optional)**: `uploads/<PREFIX>.<DATE>.csv`
- **Seller summary CSV (review)**: `uploads/<PREFIX>.<DATE>.seller_summary.csv`
- **Reports (review)**:
  - `uploads/staging_report.md` (client-facing summary)
  - `uploads/staging_report.json`
  - `uploads/staging_report_addresses.csv`
  - `uploads/staging_report_global_phones.csv`
  - `uploads/staging_report_global_emails.csv`

Everything is also copied into a dated folder inside Downloads:

- `~/Desktop/Downloads/fernando.dealmachine.clean.MM.DD.YY/` (preferred)
- or `~/Downloads/fernando.dealmachine.clean.MM.DD.YY/` (fallback)

## Why we built it this way

The “desired outcome” export contains **duplicate addresses** (multiple rows per seller/contact), but the Pete Properties Import template is **one property per row**. So the pipeline:

- **Dedupes** to one row per `Full Address`
- **Selects sellers** by preferring contacts flagged **“Likely Owner”**
- Fills seller info into the template columns (`Seller`, `Seller2`, `Seller3`, plus email/phone slots)

## How to run (CLI)

### Optional YAML config

If you want stable defaults (port, export prefix, thresholds, etc.) without typing flags every time:

- Copy `config.example.yaml` to `config.yaml`
- Edit values

The CLI will automatically load `./config.yaml` if it exists. You can also pass a config path explicitly:

```bash
uv run python -m pete_dm_clean --config path/to/config.yaml build
```

CLI flags always override config values.

Build exports (recommended):

```bash
uv run python -m pete_dm_clean build
```

Interactive numbered menu:

```bash
uv run python -m pete_dm_clean menu
```

Randomize External IDs (sometimes helps when imports only partially load):

```bash
uv run python -m pete_dm_clean build --randomize-external-ids
```

## Legacy / deprecated docs

The previous README was moved to `depreciated/README.md`.

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

- **CLI**: `pete-dm-clean` (Typer) for repeatable runs and power-user flags.
- **Web app**: FastAPI + Jinja UI at `/ui` for uploads, previews, and one-click builds.

Both interfaces call the same core pipeline: `build_staging.run_build(...)`, which produces:

- `uploads/<PREFIX>.<DATE>.xlsx` (Pete Properties Import-ready)
- `uploads/<PREFIX>.<DATE>.csv` (optional)
- `uploads/<PREFIX>.<DATE>.seller_summary.csv`
- reports + per-run logs/summaries under `uploads/`

### CLI vs Web UI (what each can do)

They overlap heavily, but they aren’t identical.

- **Web UI does (and CLI doesn’t)**:
  - **Upload** inputs via browser (client-scoped workspaces)
  - **Preview** CSV samples + “outcome preview” of latest output
  - **Download** artifacts via safe links
  - **Client management** (create/select client workspaces)
  - **Edit config** in-browser (writes to `CONFIG_PATH` / `./config.yaml`)

- **CLI does (and Web UI may not expose all of)**:
  - **Serve** the app with uvicorn flags (`pete-dm-clean serve ...`)
  - **Learning-mode call tracing** (`--trace-calls`, etc.)
  - Fine-grained **threshold overrides** via CLI/config without UI widgets

### Randomize External Ids (parity note)

- The pipeline supports External Id randomization to stabilize imports.
- **CLI**: `pete-dm-clean build --randomize-external-ids ...`
- **Web UI**: build form includes “Randomize External Ids” + optional seed/digits.

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
