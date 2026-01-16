from __future__ import annotations

from pathlib import Path
import os
import subprocess
from typing import Optional

import typer

from build_staging import run_build
from pete_dm_clean import __version__
from pete_dm_clean.config import cfg_get, load_config, load_validated_config
from pete_dm_clean.diagrams import generate_pipeline_diagram
from pete_dm_clean.db import maybe_ingest_run_json


app = typer.Typer(
    add_completion=False,
    help="pete DEAL MACHINE clean — build imports + reports + diagrams.",
)

@app.callback(invoke_without_command=True)
def _config(
    ctx: typer.Context,
    config: Optional[Path] = typer.Option(
        None,
        help="Optional YAML config path (defaults to ./config.yaml if it exists).",
    ),
):
    ctx.obj = {"raw": load_config(config), "typed": load_validated_config(config)}
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


def _optional_questionary():
    try:
        import questionary  # type: ignore  # pylint: disable=import-error

        return questionary
    except Exception:
        return None


@app.command("build")
def build(
    ctx: typer.Context,
    company_id: Optional[str] = typer.Option(None, help="Optional company UUID to scope inputs/outputs/runs/diagrams"),
    company_name: Optional[str] = typer.Option(None, help="Optional company name (stored in run record)"),
    uploads_dir: Optional[Path] = typer.Option(None, help="Where input files live (default: uploads/)"),
    desired_outcome: Optional[Path] = typer.Option(None, help="Desired-outcome CSV (auto-detect if omitted)"),
    contacts: Optional[Path] = typer.Option(None, help="Contacts CSV (auto-detect if omitted)"),
    template: Optional[Path] = typer.Option(None, help="Properties template XLSX"),
    export_prefix: Optional[str] = typer.Option(None, help="Export filename prefix"),
    export_prefix_from_input: bool = typer.Option(
        False,
        help="Derive export prefix from the selected input filename (adds '.CLEAN').",
    ),
    export_date_format: Optional[str] = typer.Option(None, help="Date format used in export filenames"),
    max_sellers: Optional[int] = typer.Option(None, help="Max seller contacts to consider (template may cap seller people)"),
    randomize_external_ids: Optional[bool] = typer.Option(None, help="Replace External Id with unique randomized ids"),
    external_id_seed: Optional[int] = typer.Option(None, help="Seed for External Id randomization"),
    external_id_digits: Optional[int] = typer.Option(None, help="Digits for randomized External Ids"),
    desktop_copy: Optional[bool] = typer.Option(None, help="Copy outputs into a dated Downloads folder"),
    desktop_copy_dir: Optional[Path] = typer.Option(None, help="Override Downloads folder (optional)"),
    desktop_subfolder_prefix: Optional[str] = typer.Option(None, help="Downloads subfolder prefix"),
    desktop_subfolder_date_format: Optional[str] = typer.Option(None, help="Downloads subfolder date format"),
    trace_calls: Optional[bool] = typer.Option(None, help="Learning mode: record function calls during the run"),
    trace_max_events: Optional[int] = typer.Option(None, help="Max call events to write to the call trace file"),
    trace_include_stdlib: Optional[bool] = typer.Option(None, help="Include stdlib/site-packages calls (very noisy)"),
    debug_report: Optional[bool] = typer.Option(None, help="Write a separate deep-dive debug report (<run_id>.debug.md/.json)"),
    debug_sample_n: Optional[int] = typer.Option(None, help="Sample size for debug report sections"),
    contacts_only: bool = typer.Option(False, help="Build using only contacts CSV (derive property rows from contacts addresses)"),
):
    """
    Build the import XLSX + CSV + seller summary + collision reports.
    """
    cfg_raw = (ctx.obj or {}).get("raw") or {}
    cfg_typed = (ctx.obj or {}).get("typed")
    env_uploads = (os.getenv("UPLOADS_DIR") or "").strip()
    eff_uploads_dir = uploads_dir or Path(cfg_get(cfg_raw, "build.uploads_dir", env_uploads or "uploads"))
    # If company_id is provided, scope inputs/outputs under uploads/companies/<company_id>/
    eff_inputs_dir = None
    eff_outputs_dir = None
    if company_id:
        from pete_dm_clean.companies import company_paths, ensure_company_dirs

        paths = company_paths(uploads_dir=eff_uploads_dir, company_id=company_id)
        ensure_company_dirs(paths)
        eff_inputs_dir = paths.inputs_dir
        eff_outputs_dir = paths.outputs_dir
    eff_template = template or Path(cfg_get(cfg_raw, "build.template", "uploads/templates/Properties Template (15).xlsx"))

    gen_defaults = None
    if cfg_typed is not None:
        try:
            gen_defaults = cfg_typed.generators.pete_properties_import
        except Exception:
            gen_defaults = None

    eff_export_prefix = export_prefix or (
        gen_defaults.export_prefix
        if gen_defaults
        else str(cfg_get(cfg_raw, "build.export_prefix", "PETE.DM.FERNANDO.CLEAN"))
    )
    if export_prefix is None and export_prefix_from_input:
        # Let run_build compute this once it has resolved the real input file.
        eff_export_prefix = "AUTO_FROM_INPUT"
    eff_export_date_format = export_date_format or (
        gen_defaults.export_date_format if gen_defaults else str(cfg_get(cfg_raw, "build.export_date_format", "%m.%d.%y"))
    )
    eff_max_sellers = int(
        max_sellers if max_sellers is not None else (gen_defaults.max_sellers if gen_defaults else cfg_get(cfg_raw, "build.max_sellers", 5))
    )
    eff_desktop_copy = bool(desktop_copy if desktop_copy is not None else cfg_get(cfg_raw, "build.desktop_copy", True))
    eff_desktop_subfolder_prefix = desktop_subfolder_prefix or str(
        cfg_get(cfg_raw, "build.desktop_subfolder_prefix", "fernando.dealmachine.clean")
    )
    eff_desktop_subfolder_date_format = desktop_subfolder_date_format or str(
        cfg_get(cfg_raw, "build.desktop_subfolder_date_format", "%m.%d.%y")
    )
    eff_randomize_external_ids = bool(randomize_external_ids) if randomize_external_ids is not None else False
    eff_external_id_digits = int(external_id_digits if external_id_digits is not None else 7)
    eff_trace_calls = bool(trace_calls) if trace_calls is not None else False
    eff_trace_max_events = int(trace_max_events if trace_max_events is not None else 50000)
    eff_trace_include_stdlib = bool(trace_include_stdlib) if trace_include_stdlib is not None else False
    eff_debug_report = bool(debug_report) if debug_report is not None else (gen_defaults.debug_report if gen_defaults else False)
    eff_debug_sample_n = int(debug_sample_n if debug_sample_n is not None else (gen_defaults.debug_sample_n if gen_defaults else 25))

    match_warn_pct = float(cfg_get(cfg_raw, "thresholds.match_warn_pct", 95.0))
    missing_warn = int(cfg_get(cfg_raw, "thresholds.missing_seller_warn_count", 1))

    result = run_build(
        uploads_dir=eff_uploads_dir,
        inputs_dir=eff_inputs_dir,
        outputs_dir=eff_outputs_dir,
        desired_outcome=desired_outcome,
        contacts=contacts,
        template=eff_template,
        export_prefix=eff_export_prefix,
        export_date_format=eff_export_date_format,
        out_xlsx=None,
        out_csv=None,
        seller_summary_csv=None,
        max_sellers=eff_max_sellers,
        randomize_external_ids_enabled=eff_randomize_external_ids,
        external_id_seed=external_id_seed,
        external_id_digits=eff_external_id_digits,
        report_json=eff_uploads_dir / "staging_report.json",
        report_addresses_csv=eff_uploads_dir / "staging_report_addresses.csv",
        report_global_phones_csv=eff_uploads_dir / "staging_report_global_phones.csv",
        report_global_emails_csv=eff_uploads_dir / "staging_report_global_emails.csv",
        report_md=eff_uploads_dir / "staging_report.md",
        desktop_copy=eff_desktop_copy,
        desktop_copy_dir=desktop_copy_dir,
        desktop_subfolder_prefix=eff_desktop_subfolder_prefix,
        desktop_subfolder_date_format=eff_desktop_subfolder_date_format,
        trace_calls=eff_trace_calls,
        trace_max_events=eff_trace_max_events,
        trace_include_stdlib=eff_trace_include_stdlib,
        debug_report=eff_debug_report,
        debug_sample_n=eff_debug_sample_n,
        status_match_warn_pct=match_warn_pct,
        status_missing_seller_warn_count=missing_warn,
        company_id=company_id,
        company_name=company_name,
        contacts_only=contacts_only,
    )

    # Optional DB ingestion (metadata only). DB is enabled via DB_URL / DB_PATH / DB_ENABLED=1.
    try:
        runs_dir = (eff_uploads_dir / "runs" / str(company_id)) if company_id else (eff_uploads_dir / "runs")
        latest_json = sorted(runs_dir.glob("*.json"))[-1] if runs_dir.exists() else None
        if latest_json is not None:
            maybe_ingest_run_json(uploads_dir=eff_uploads_dir, run_json_path=latest_json)
    except Exception:
        # best-effort; never fail the build due to metadata indexing
        pass

    typer.echo(f"Wrote: {result.out_xlsx}")
    typer.echo(f"Wrote: {result.out_csv}")
    if result.seller_summary_csv.exists():
        typer.echo(f"Wrote: {result.seller_summary_csv}")
    typer.echo(f"rows: {result.staging_rows} unique_addresses: {result.staging_unique_addresses}")
    typer.echo(f"Report (md): {result.report_md}")
    if result.desktop_export_dir:
        typer.echo(f"Copied to: {result.desktop_export_dir}")


@app.command("menu")
def menu():
    """
    Interactive numbered menu (uses questionary if installed; otherwise falls back to a simple prompt).
    """
    q = _optional_questionary()
    # Create a minimal context so calling build() directly works (and uses config defaults).
    ctx = typer.Context(app)
    ctx.obj = {"raw": load_config(None), "typed": load_validated_config(None)}
    if q:
        choice = q.select(
            f"pete-dm-clean v{__version__} — choose an action",
            choices=[
                "1) Build clean import files + reports",
                "2) Exit",
            ],
        ).ask()
        if not choice:
            raise typer.Exit(code=0)
        if choice.startswith("1"):
            build(ctx=ctx)  # run with defaults
            raise typer.Exit(code=0)
        raise typer.Exit(code=0)

    typer.echo(f"pete-dm-clean v{__version__}")
    typer.echo("1) Build clean import files + reports")
    typer.echo("2) Exit")
    resp = input("Select an option (1-2): ").strip()
    if resp == "1":
        build(ctx=ctx)
    raise typer.Exit(code=0)


@app.command("diagram")
def diagram(
    ctx: typer.Context,
    uploads_dir: Optional[Path] = typer.Option(None, help="Uploads directory (default: uploads/)"),
    code_path: Path = typer.Option(Path("build_staging.py"), help="Python file to diagram"),
    name: Optional[str] = typer.Option(None, help="Optional diagram name override"),
):
    """
    Generate a pipeline diagram into uploads/flowcharts/.
    """
    cfg_raw = (ctx.obj or {}).get("raw") or {}
    env_uploads = (os.getenv("UPLOADS_DIR") or "").strip()
    eff_uploads_dir = uploads_dir or Path(cfg_get(cfg_raw, "build.uploads_dir", env_uploads or "uploads"))
    res = generate_pipeline_diagram(uploads_dir=eff_uploads_dir, code_path=code_path, name=name)
    typer.echo(f"Wrote: {res.flow_txt}")
    typer.echo(f"Wrote: {res.summary_md}")


@app.command("serve")
def serve(
    ctx: typer.Context,
    host: Optional[str] = typer.Option(None, help="Bind host"),
    port: Optional[int] = typer.Option(None, help="Bind port (default is intentionally non-8000)"),
    reload: Optional[bool] = typer.Option(None, help="Auto-reload (dev)"),
):
    """
    Run the FastAPI diagram viewer with Uvicorn.
    """
    cfg_raw = (ctx.obj or {}).get("raw") or {}
    host = host or str(cfg_get(cfg_raw, "serve.host", "127.0.0.1"))
    port = int(port if port is not None else cfg_get(cfg_raw, "serve.port", 8765))
    reload = bool(reload) if reload is not None else bool(cfg_get(cfg_raw, "serve.reload", True))

    cmd = [
        "uvicorn",
        "pete_dm_clean.server:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if reload:
        cmd.append("--reload")
    typer.echo("Running: " + " ".join(cmd))
    typer.echo(f"Open: http://{host}:{port}/")
    raise typer.Exit(code=subprocess.call(cmd))


def main():
    app()

