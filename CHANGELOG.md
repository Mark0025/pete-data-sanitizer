## Changelog

All notable changes to this project will be documented in this file.

### Unreleased

- Added “contacts-only” build mode: upload only a DealMachine contacts export and derive one row per property from `associated_property_address_full`.
- Added client/company scoping for inputs/outputs/runs/diagrams (UUID-backed under the hood; UI uses “Client” terminology).
- Added safe download links in the UI for build artifacts (XLSX/CSV/seller summary/report).
- Added UI help popups with 5-row previews (all columns) and an “outcome preview” (latest output sample).
- Hardened UI build errors with friendly pages + logging, instead of raw 500s.
- Added “deep” runtime diagram enrichment + end-status node (OK/WARN/FAIL + reasons) driven by runtime metrics.
- Added Loguru logging to per-run logs (`uploads/runs/<run_id>.log`).
- Added generator decorator for Pete template inheritance (registry + enforced column order/shape).
- Added YAML config validation via Pydantic `AppConfig` and wired generator defaults into CLI.
- Added Ruff + Pyright scaffolding and minimal pytest suite for template inheritance/config/company paths.

### 0.0.4

- Added deep-dive runtime diagram artifacts (`acki_run_<run_id>.deep.*`) generated when `--debug-report` is enabled.
- Improved server index to surface latest run + deep-dive artifacts for debugging.

### 0.0.5

- Added optional YAML config support (`config.yaml`) with `config.example.yaml`.
- CLI can load config values as defaults (CLI flags still override).
- End-status thresholds (OK/WARN/FAIL) are configurable via config.

### 0.0.6

- Added a Jinja2 UI at `/ui` (dashboard, upload, build form, preview, settings editor).
- Added `python-multipart` dependency for upload + form handling.

### 0.0.3

- Added diagram generation outputs under `uploads/flowcharts/` (code flow + data stats summary).
- Added FastAPI app to view generated diagrams and summaries, intended to be run with Uvicorn.
- Added new CLI commands: `diagram` and `serve`.

### 0.0.2

- Added CLI entrypoint `pete-dm-clean` with `build` and `menu` commands.
- Refactored `build_staging.py` to expose `run_build(...)` for programmatic/CLI use.
- Added export naming support (`PETE.DM.FERNANDO.CLEAN.<date>.xlsx` + `.csv`) and seller summary CSV.
- Added reports:
  - `staging_report.json`
  - `staging_report.md` (client-facing)
  - per-address + global phone/email collision CSVs
- Added optional External Id randomization (`--randomize-external-ids`) for import stability.
- Added Downloads copy to dated folder (`fernando.dealmachine.clean.<date>`).

