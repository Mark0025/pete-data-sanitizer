from __future__ import annotations

import html
import os
import re
import shutil
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from pete_dm_clean.diagrams import default_flowcharts_dir, generate_pipeline_diagram
from pete_dm_clean.companies import load_companies, save_companies, new_company_id, company_paths, ensure_company_dirs
from pete_dm_clean.config import load_config, default_config_path
from pete_dm_clean.db import init_db_if_enabled, maybe_ingest_run_json
from pete_dm_clean.logging import configure_logging, get_logger
from build_staging import run_build


def _default_uploads_dir() -> Path:
    """
    Resolve uploads directory for server mode.

    Order of precedence:
    1) UPLOADS_DIR env var
    2) ./uploads (local default)
    """
    env = (os.getenv("UPLOADS_DIR") or "").strip()
    return Path(env) if env else Path("uploads")


def _list_diagrams(flow_dir: Path) -> list[str]:
    """
    Return diagram names relative to flow_dir, without extensions.
    Supports nested subfolders (company scoping).
    """
    names: set[str] = set()
    for p in flow_dir.glob("**/*.flow.txt"):
        rel = p.relative_to(flow_dir).as_posix()
        if rel.endswith(".flow.txt"):
            rel = rel[: -len(".flow.txt")]
        names.add(rel)
    return sorted(names)

def _latest_file(dir_path: Path, glob_pat: str) -> Path | None:
    files = sorted(dir_path.glob(glob_pat))
    return files[-1] if files else None

def _run_id_from_diagram_name(name: str) -> str | None:
    """
    Extract run_id from names like:
    - acki_run_<run_id>
    - acki_run_<run_id>.deep
    """
    base = Path(name).name
    m = re.match(r"^acki_run_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})(?:\.deep)?$", base)
    return m.group(1) if m else None

def _company_id_from_diagram_name(name: str) -> str | None:
    """
    If name is like "<company_id>/acki_run_<run_id>" return company_id.
    Otherwise None.
    """
    parts = Path(name).parts
    if len(parts) >= 2:
        cid = parts[0]
        if re.fullmatch(r"[0-9a-fA-F-]{36}", cid):
            return cid
    return None


def _safe_filename(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^A-Za-z0-9._ ()\\-]+", "_", name).strip()
    return name[:180] if name else "upload.bin"


def _list_upload_candidates(uploads_dir: Path) -> dict[str, list[Path]]:
    # Keep it simple: use filename hints; user can override by selecting.
    csvs = sorted(uploads_dir.glob("*.csv"))
    xlsxs = sorted(uploads_dir.glob("*.xlsx"))
    templates = sorted((uploads_dir / "templates").glob("*.xlsx")) if (uploads_dir / "templates").exists() else []
    return {
        "desired_outcome": [p for p in csvs if "desired" in p.name.lower() or "outcome" in p.name.lower()] + csvs,
        "contacts": [p for p in csvs if "contact" in p.name.lower()] + csvs,
        "template": templates + xlsxs,
    }


def _has_any_csv(dir_path: Path) -> bool:
    return any(dir_path.glob("*.csv"))


def create_app(uploads_dir: Path = Path("uploads")) -> FastAPI:
    fastapi_app = FastAPI(title="pete DM clean — viewer", version="0.0.6")
    configure_logging()
    log = get_logger()
    # Optional metadata DB (SQLite/Postgres). Enabled via DB_URL / DB_PATH / DB_ENABLED=1.
    try:
        init_db_if_enabled(uploads_dir=Path(uploads_dir))
    except Exception:
        # best-effort; DB must never prevent server start
        pass
    # global roots; company scoping uses subfolders
    flow_root = default_flowcharts_dir(uploads_dir)
    flow_root.mkdir(parents=True, exist_ok=True)
    runs_root = Path(uploads_dir) / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "ui" / "templates"))

    @fastapi_app.get("/healthz", response_class=PlainTextResponse)
    def healthz():
        return PlainTextResponse("ok")

    @fastapi_app.get("/", response_class=HTMLResponse)
    def index():
        names = _list_diagrams(flow_root)
        links = "\n".join([f'<li><a href="/diagram/{html.escape(n)}">{html.escape(n)}</a></li>' for n in names])

        latest_summary = _latest_file(runs_root, "*.summary.md")
        latest_run_id = latest_summary.stem.replace(".summary", "") if latest_summary else None
        latest_acki = f"acki_run_{latest_run_id}" if latest_run_id else None
        deep_exists = (flow_root / f"{latest_acki}.deep.flow.txt").exists() if latest_acki else False

        # List last N runs (summary + optional debug)
        run_summaries = sorted(runs_root.glob("*.summary.md"))[-15:]
        run_items = []
        for p in reversed(run_summaries):
            rid = p.stem.replace(".summary", "")
            debug_path = runs_root / f"{rid}.debug.md"
            run_items.append(
                f"<li><code>{html.escape(rid)}</code> "
                f'(<a href="/runs/{html.escape(rid)}/summary">summary</a>'
                + (f' | <a href="/runs/{html.escape(rid)}/debug">debug</a>' if debug_path.exists() else "")
                + ")</li>"
            )
        runs_html = "\n".join(run_items) if run_items else "<li>(no runs yet)</li>"

        return HTMLResponse(
            f"""
            <html>
              <head><title>pete DM clean — diagrams</title></head>
              <body>
                <h2>pete DM clean — index</h2>

                <h3>Latest run</h3>
                <ul>
                  <li>latest run_id: <code>{html.escape(latest_run_id or "none")}</code></li>
                  <li><a href="/runs/latest">/runs/latest</a> (summary)</li>
                  <li><a href="/runs/latest/debug">/runs/latest/debug</a> (debug, if generated)</li>
                  <li>
                    latest diagrams:
                    {(
                        f'<a href="/diagram/{html.escape(latest_acki)}">acki</a>'
                        + (
                            f' | <a href="/diagram/{html.escape(latest_acki)}.deep">acki.deep</a>'
                            if deep_exists else ''
                          )
                      ) if latest_acki else '(none)'}
                  </li>
                </ul>

                <h3>Recent runs</h3>
                <ul>{runs_html}</ul>

                <h3>Diagrams</h3>
                <p><a href="/generate">Generate latest pipeline diagram</a></p>
                <ul>{links}</ul>
              </body>
            </html>
            """
        )

    # ---------------------------
    # Jinja2 UI (dashboard CRUD)
    # ---------------------------
    @fastapi_app.get("/ui", response_class=HTMLResponse)
    def ui_dashboard(request: Request, company_id: str | None = None):
        uploads_p = Path(uploads_dir)
        companies = load_companies(uploads_p)
        if not company_id and companies:
            company_id = next(iter(companies.keys()))
        company_name = companies.get(company_id, {}).get("name") if company_id else None

        # Company-scoped paths
        paths = None
        flow_dir = flow_root
        runs_dir = runs_root
        inputs_dir = uploads_p
        if company_id:
            paths = company_paths(uploads_dir=uploads_p, company_id=company_id)
            ensure_company_dirs(paths)
            flow_dir = default_flowcharts_dir(uploads_p, company_id=company_id)
            runs_dir = runs_root / company_id
            inputs_dir = paths.inputs_dir

        names = _list_diagrams(flow_dir)
        latest_summary = _latest_file(runs_dir, "*.summary.md") if runs_dir.exists() else None
        latest_run_id = latest_summary.stem.replace(".summary", "") if latest_summary else None
        latest_debug = (runs_dir / f"{latest_run_id}.debug.md") if latest_run_id else None
        cfg = load_config(None)

        candidates = _list_upload_candidates(Path(inputs_dir))

        # Most recent runs
        run_summaries = sorted(runs_dir.glob("*.summary.md"))[-20:] if runs_dir.exists() else []
        recent_runs = []
        for p in reversed(run_summaries):
            rid = p.stem.replace(".summary", "")
            recent_runs.append(
                {
                    "run_id": rid,
                    "has_debug": (runs_dir / f"{rid}.debug.md").exists(),
                    "status": None,  # populated lazily by summary page; keep UI fast
                }
            )

        # Prefer showing Acki diagrams first
        diagrams = [n for n in names if n.startswith("acki_run_")] + [n for n in names if not n.startswith("acki_run_")]

        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "title": "Dashboard",
                "uploads_dir": str(uploads_dir),
                "company_id": company_id or "",
                "company_name": company_name or "",
                "companies": [{"id": cid, "name": v.get("name","")} for cid, v in sorted(companies.items())],
                "latest_run_id": latest_run_id,
                "latest_has_debug": bool(latest_debug and latest_debug.exists()),
                "recent_runs": recent_runs,
                "diagrams": diagrams,
                "candidates": candidates,
                "cfg": cfg,
            },
        )

    @fastapi_app.get("/ui/preview_snippet", response_class=HTMLResponse)
    def ui_preview_snippet(
        company_id: str = "",
        kind: str = "desired_outcome",
        filename: str = "",
        n: int = 5,
    ):
        """
        Return a tiny HTML preview (first N rows) for the selected CSV within the client scope.
        This is used by the dashboard help pop-up.
        """
        kind = (kind or "").strip().lower()
        if kind not in {"desired_outcome", "contacts"}:
            raise HTTPException(status_code=400, detail="invalid kind")

        uploads_p = Path(uploads_dir)
        inputs_dir = uploads_p
        if company_id:
            paths = company_paths(uploads_dir=uploads_p, company_id=company_id)
            ensure_company_dirs(paths)
            inputs_dir = paths.inputs_dir

        if not filename:
            return HTMLResponse("<div class='muted'>Select a file first (or upload one).</div>")

        path = (inputs_dir / filename).resolve()
        # Safety: keep reads inside the expected inputs dir
        try:
            _ = path.relative_to(inputs_dir.resolve())
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="invalid filename") from exc

        if not path.exists():
            return HTMLResponse("<div class='muted'>File not found in this client workspace.</div>")

        try:
            import pandas as pd

            df = pd.read_csv(path, nrows=max(1, min(int(n), 20)))
            # All columns, first N rows
            html_table = df.to_html(index=False, escape=True, border=0)
            return HTMLResponse(
                f"<div class='muted' style='margin-bottom:6px'><span class='mono'>{html.escape(path.name)}</span> (first {len(df)} rows)</div>"
                + html_table
            )
        except Exception as e:  # noqa: BLE001
            log.warning("ui_preview_snippet_failed company_id={} file={} err={}", company_id, filename, str(e))
            return HTMLResponse("<div class='muted'>Could not preview file (parse error).</div>")

    @fastapi_app.get("/ui/output_preview_snippet", response_class=HTMLResponse)
    def ui_output_preview_snippet(
        company_id: str = "",
        n: int = 5,
    ):
        """
        Show a tiny preview of the *latest build output* (what you would upload),
        scoped to the selected client.
        """
        runs_dir = runs_root / company_id if company_id else runs_root
        if not runs_dir.exists():
            return HTMLResponse("<div class='muted'>No runs yet for this client.</div>")

        latest_json = _latest_file(runs_dir, "*.json")
        if latest_json is None:
            return HTMLResponse("<div class='muted'>No runs yet for this client.</div>")

        try:
            import json
            import pandas as pd

            run = json.loads(latest_json.read_text(encoding="utf-8"))
            out_csv = (run.get("outputs") or {}).get("out_csv")
            out_xlsx = (run.get("outputs") or {}).get("out_xlsx")
            out_path = Path(out_csv or out_xlsx or "")
            if not str(out_path):
                return HTMLResponse("<div class='muted'>Latest run has no recorded outputs.</div>")
            if not out_path.exists():
                return HTMLResponse("<div class='muted'>Latest output file not found on disk.</div>")

            if out_path.suffix.lower() == ".csv":
                # Read as strings to avoid float artifacts like "5551112222.0" in previews.
                df = pd.read_csv(
                    out_path,
                    nrows=max(1, min(int(n), 20)),
                    dtype=str,
                    keep_default_na=False,
                )
            else:
                df = pd.read_excel(out_path, nrows=max(1, min(int(n), 20)))

            html_table = df.to_html(index=False, escape=True, border=0)
            return HTMLResponse(
                f"<div class='muted' style='margin-bottom:6px'><b>Outcome preview</b>: <span class='mono'>{html.escape(out_path.name)}</span> (first {len(df)} rows)</div>"
                + html_table
            )
        except Exception as e:  # noqa: BLE001
            log.warning("ui_output_preview_snippet_failed company_id={} err={}", company_id, str(e))
            return HTMLResponse("<div class='muted'>Could not preview latest output.</div>")

    @fastapi_app.post("/ui/company/create", response_class=RedirectResponse)
    async def ui_company_create(company_name: str = Form(...)):
        uploads_p = Path(uploads_dir)
        companies = load_companies(uploads_p)
        cid = new_company_id()
        companies[cid] = {"name": company_name.strip()}
        save_companies(uploads_p, companies)
        # create dirs
        paths = company_paths(uploads_dir=uploads_p, company_id=cid)
        ensure_company_dirs(paths)
        return RedirectResponse(url=f"/ui?company_id={cid}", status_code=303)

    @fastapi_app.post("/ui/upload", response_class=RedirectResponse)
    async def ui_upload(
        request: Request,
        company_id: str = Form(""),
        kind: str = Form(...),
        file: UploadFile = File(...),
    ):
        # kind: desired_outcome | contacts | template
        kind = kind.strip().lower()
        if kind not in {"desired_outcome", "contacts", "template"}:
            raise HTTPException(status_code=400, detail="invalid kind")
        safe = _safe_filename(file.filename or "upload.bin")
        lower = safe.lower()
        # Basic type validation to prevent confusing mis-uploads.
        if kind in {"desired_outcome", "contacts"} and not lower.endswith(".csv"):
            return templates.TemplateResponse(
                "error.html",
                {
                    "request": request,
                    "title": "Upload error",
                    "company_id": company_id,
                    "message": "This upload type expects a CSV file.",
                    "details": f"Got filename: {safe}",
                },
                status_code=400,
            )
        if kind == "template" and not (lower.endswith(".xlsx") or lower.endswith(".xls")):
            return templates.TemplateResponse(
                "error.html",
                {
                    "request": request,
                    "title": "Upload error",
                    "company_id": company_id,
                    "message": "Template upload expects an Excel file (.xlsx).",
                    "details": f"Got filename: {safe}",
                },
                status_code=400,
            )
        uploads_p = Path(uploads_dir)
        dest_dir = uploads_p
        if company_id:
            paths = company_paths(uploads_dir=uploads_p, company_id=company_id)
            ensure_company_dirs(paths)
            dest_dir = paths.templates_dir if kind == "template" else paths.inputs_dir
        else:
            dest_dir = (uploads_p / "templates") if kind == "template" else uploads_p
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / safe
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        return RedirectResponse(url=f"/ui?company_id={company_id}" if company_id else "/ui", status_code=303)

    @fastapi_app.post("/ui/build", response_class=HTMLResponse)
    async def ui_build(
        request: Request,
        company_id: str = Form(""),
        desired_outcome: str = Form(""),
        contacts: str = Form(""),
        template: str = Form(""),
        export_prefix: str = Form("PETE.DM.FERNANDO.CLEAN"),
        export_prefix_from_input: bool = Form(False),
        export_date_format: str = Form("%m.%d.%y"),
        max_sellers: int = Form(5),
        randomize_external_ids: bool = Form(False),
        external_id_seed: int | None = Form(None),
        external_id_digits: int = Form(10),
        debug_report: bool = Form(False),
        no_desktop_copy: bool = Form(False),
        contacts_only: bool = Form(False),
    ):
        # Resolve file paths relative to uploads/
        uploads_p = Path(uploads_dir)
        inputs_dir = uploads_p
        outputs_dir = uploads_p
        company_name = None
        if company_id:
            companies = load_companies(uploads_p)
            company_name = companies.get(company_id, {}).get("name")
            paths = company_paths(uploads_dir=uploads_p, company_id=company_id)
            ensure_company_dirs(paths)
            inputs_dir = paths.inputs_dir
            outputs_dir = paths.outputs_dir

        # If this client has no CSV inputs yet and user left "(auto)",
        # fall back to shared uploads/ so new clients can still run using existing data.
        if company_id and (not desired_outcome) and (not contacts) and (not _has_any_csv(inputs_dir)):
            inputs_dir = uploads_p

        desired_p = (inputs_dir / desired_outcome) if desired_outcome else None
        contacts_p = (inputs_dir / contacts) if contacts else None
        # template can be either relative like "templates/foo.xlsx" or direct filename
        if template:
            template_p = inputs_dir / template
        else:
            template_p = inputs_dir / "templates" / "Properties Template (15).xlsx"

        # Template fallback: if client doesn't have it, use shared default template.
        if not template_p.exists():
            shared_template = uploads_p / "templates" / "Properties Template (15).xlsx"
            if shared_template.exists():
                template_p = shared_template

        try:
            eff_export_prefix = "AUTO_FROM_INPUT" if bool(export_prefix_from_input) else export_prefix
            result = run_build(
                uploads_dir=uploads_p,
                inputs_dir=inputs_dir,
                outputs_dir=outputs_dir,
                desired_outcome=desired_p,
                contacts=contacts_p,
                template=template_p,
                export_prefix=eff_export_prefix,
                export_date_format=export_date_format,
                out_xlsx=None,
                out_csv=None,
                seller_summary_csv=None,
                max_sellers=int(max_sellers),
                randomize_external_ids_enabled=bool(randomize_external_ids),
                external_id_seed=external_id_seed,
                external_id_digits=int(external_id_digits),
                report_json=uploads_p / "staging_report.json",
                report_addresses_csv=uploads_p / "staging_report_addresses.csv",
                report_global_phones_csv=uploads_p / "staging_report_global_phones.csv",
                report_global_emails_csv=uploads_p / "staging_report_global_emails.csv",
                report_md=uploads_p / "staging_report.md",
                desktop_copy=not bool(no_desktop_copy),
                desktop_copy_dir=None,
                desktop_subfolder_prefix="fernando.dealmachine.clean",
                desktop_subfolder_date_format="%m.%d.%y",
                debug_report=bool(debug_report),
                debug_sample_n=25,
                company_id=company_id or None,
                company_name=company_name,
                contacts_only=bool(contacts_only),
            )
        except FileNotFoundError as e:
            log.warning("ui_build_missing_inputs company_id={} err={}", company_id, str(e))
            return templates.TemplateResponse(
                "error.html",
                {
                    "request": request,
                    "title": "Build error",
                    "company_id": company_id,
                    "message": "Missing inputs for this client. Upload/select the desired outcome + contacts CSV first.",
                    "details": str(e),
                },
                status_code=400,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("ui_build_failed company_id={}", company_id)
            return templates.TemplateResponse(
                "error.html",
                {
                    "request": request,
                    "title": "Build error",
                    "company_id": company_id,
                    "message": "Build failed (unexpected error).",
                    "details": str(e),
                },
                status_code=500,
            )

        runs_dir = (runs_root / company_id) if company_id else runs_root
        run_id = _latest_file(runs_dir, "*.summary.md").stem.replace(".summary", "")
        # Optional DB ingestion (metadata only)
        try:
            run_json = runs_dir / f"{run_id}.json"
            if run_json.exists():
                maybe_ingest_run_json(uploads_dir=uploads_p, run_json_path=run_json)
        except Exception:
            pass
        acki = f"acki_run_{run_id}"
        flow_dir = default_flowcharts_dir(uploads_p, company_id=company_id or None)
        deep_exists = (flow_dir / f"{acki}.deep.flow.txt").exists()

        return templates.TemplateResponse(
            "build_done.html",
            {
                "request": request,
                "title": "Build complete",
                "run_id": run_id,
                "acki": acki,
                "deep_exists": deep_exists,
                "out_xlsx": str(result.out_xlsx),
                "out_csv": str(result.out_csv),
                "report_md": str(result.report_md),
                "seller_summary_csv": str(result.seller_summary_csv),
                "company_id": company_id,
                "desktop_export_dir": str(result.desktop_export_dir) if result.desktop_export_dir else "",
            },
        )

    @fastapi_app.get("/ui/settings", response_class=HTMLResponse)
    def ui_settings(request: Request):
        cfg_path = default_config_path()
        text = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else ""
        return templates.TemplateResponse(
            "settings.html",
            {"request": request, "title": "Settings", "config_text": text, "config_path": str(cfg_path)},
        )

    @fastapi_app.post("/ui/settings", response_class=RedirectResponse)
    async def ui_settings_save(config_text: str = Form("")):
        cfg_path = default_config_path()
        if cfg_path.exists():
            backup = cfg_path.with_suffix(cfg_path.suffix + ".bak")
            backup.write_text(cfg_path.read_text(encoding="utf-8"), encoding="utf-8")
        cfg_path.write_text(config_text.strip() + "\n" if config_text.strip() else "", encoding="utf-8")
        return RedirectResponse(url="/ui/settings", status_code=303)

    @fastapi_app.get("/ui/preview", response_class=HTMLResponse)
    def ui_preview(request: Request):
        # Keep preview light: show template columns and counts from existing reports.
        uploads_p = Path(uploads_dir)
        template_p = uploads_p / "templates" / "Properties Template (15).xlsx"
        template_cols: list[str] = []
        if template_p.exists():
            try:
                import pandas as pd

                df = pd.read_excel(template_p)
                template_cols = [str(c) for c in df.columns.tolist()]
            except Exception:  # noqa: BLE001
                template_cols = []

        latest_summary = _latest_file(runs_root, "*.summary.md")
        latest_run_id = latest_summary.stem.replace(".summary", "") if latest_summary else None
        latest_debug = (runs_root / f"{latest_run_id}.debug.md") if latest_run_id else None

        return templates.TemplateResponse(
            "preview.html",
            {
                "request": request,
                "title": "Preview",
                "template_path": str(template_p),
                "template_cols": template_cols,
                "latest_run_id": latest_run_id,
                "latest_has_debug": bool(latest_debug and latest_debug.exists()),
            },
        )

    @fastapi_app.get("/generate", response_class=HTMLResponse)
    def generate():
        res = generate_pipeline_diagram(uploads_dir=uploads_dir, code_path=Path("build_staging.py"))
        return HTMLResponse(
            f"""
            <html>
              <head><title>Generated</title></head>
              <body>
                <h2>Generated</h2>
                <ul>
                  <li><a href="/diagram/{html.escape(res.name)}">{html.escape(res.name)}</a></li>
                  <li><a href="/diagram/{html.escape(res.name)}/raw">raw</a></li>
                  <li><a href="/diagram/{html.escape(res.name)}/summary">summary</a></li>
                </ul>
              </body>
            </html>
            """
        )

    @fastapi_app.get("/diagram/{name:path}", response_class=HTMLResponse)
    def diagram(name: str):
        # Try company-scoped first if name contains "<company_id>/...".
        flow_path = flow_root / f"{name}.flow.txt"
        if not flow_path.exists():
            raise HTTPException(status_code=404, detail="diagram not found")
        flow = flow_path.read_text(encoding="utf-8")
        js_safe_flow = flow.replace("`", "\\`")
        run_id = _run_id_from_diagram_name(name)
        company_id = _company_id_from_diagram_name(name)
        run_links = ""
        run_panel = ""
        if run_id:
            scoped_runs = (runs_root / company_id) if company_id else runs_root
            summary_path = scoped_runs / f"{run_id}.summary.md"
            debug_path = scoped_runs / f"{run_id}.debug.md"
            summary_link = f'/runs/{html.escape(run_id)}/summary'
            debug_link = f'/runs/{html.escape(run_id)}/debug'
            run_links = (
                f'<p><b>Run:</b> <code>{html.escape(run_id)}</code> '
                f'(<a href="{summary_link}">summary</a>'
                + (f' | <a href="{debug_link}">debug</a>' if debug_path.exists() else "")
                + ")</p>"
            )
            if summary_path.exists():
                summary_text = html.escape(summary_path.read_text(encoding="utf-8"))
                run_panel = (
                    "<details open>"
                    "<summary><b>Run summary (inline)</b></summary>"
                    f"<pre style='white-space:pre-wrap'>{summary_text}</pre>"
                    "</details>"
                )
        # Client-side rendering using flowchart.js (CDN). This keeps server fully pythonic.
        return HTMLResponse(
            f"""
            <html>
              <head>
                <title>{html.escape(name)}</title>
                <script src="https://cdnjs.cloudflare.com/ajax/libs/raphael/2.3.0/raphael.min.js"></script>
                <script src="https://cdnjs.cloudflare.com/ajax/libs/flowchart/1.18.0/flowchart.min.js"></script>
              </head>
              <body>
                <h2>{html.escape(name)}</h2>
                <p>
                  <a href="/diagram/{html.escape(name)}/raw">raw</a> |
                  <a href="/diagram/{html.escape(name)}/summary">summary</a>
                </p>
                {run_links}
                <div id="diagram"></div>
                <script>
                  const code = `{js_safe_flow}`;
                  const chart = flowchart.parse(code);
                  chart.drawSVG('diagram');
                </script>
                <hr/>
                {run_panel}
                <details>
                  <summary><b>Raw diagram text</b></summary>
                  <pre style="white-space:pre-wrap">{html.escape(flow)}</pre>
                </details>
              </body>
            </html>
            """
        )

    @fastapi_app.get("/diagram/{name:path}/raw", response_class=PlainTextResponse)
    def diagram_raw(name: str):
        flow_path = flow_root / f"{name}.flow.txt"
        if not flow_path.exists():
            raise HTTPException(status_code=404, detail="diagram not found")
        return PlainTextResponse(flow_path.read_text(encoding="utf-8"))

    @fastapi_app.get("/diagram/{name:path}/summary", response_class=PlainTextResponse)
    def diagram_summary(name: str):
        summary_path = flow_root / f"{name}.summary.md"
        if not summary_path.exists():
            raise HTTPException(status_code=404, detail="summary not found")
        return PlainTextResponse(summary_path.read_text(encoding="utf-8"))

    @fastapi_app.get("/runs/latest", response_class=PlainTextResponse)
    def runs_latest():
        runs_dir = Path(uploads_dir) / "runs"
        if not runs_dir.exists():
            raise HTTPException(status_code=404, detail="no runs directory")
        files = sorted(runs_dir.glob("*.summary.md"))
        if not files:
            raise HTTPException(status_code=404, detail="no runs found")
        return PlainTextResponse(files[-1].read_text(encoding="utf-8"))

    @fastapi_app.get("/runs/latest/debug", response_class=PlainTextResponse)
    def runs_latest_debug():
        runs_dir = Path(uploads_dir) / "runs"
        if not runs_dir.exists():
            raise HTTPException(status_code=404, detail="no runs directory")
        files = sorted(runs_dir.glob("*.debug.md"))
        if not files:
            raise HTTPException(status_code=404, detail="no debug reports found (run build with --debug-report)")
        return PlainTextResponse(files[-1].read_text(encoding="utf-8"))

    @fastapi_app.get("/runs/{run_id}/summary", response_class=PlainTextResponse)
    def runs_summary(run_id: str, company_id: str | None = None):
        runs_dir = (runs_root / company_id) if company_id else runs_root
        path = runs_dir / f"{run_id}.summary.md"
        if not path.exists():
            raise HTTPException(status_code=404, detail="summary not found for run_id")
        return PlainTextResponse(path.read_text(encoding="utf-8"))

    @fastapi_app.get("/runs/{run_id}/debug", response_class=PlainTextResponse)
    def runs_debug(run_id: str, company_id: str | None = None):
        runs_dir = (runs_root / company_id) if company_id else runs_root
        path = runs_dir / f"{run_id}.debug.md"
        if not path.exists():
            raise HTTPException(status_code=404, detail="debug report not found for run_id")
        return PlainTextResponse(path.read_text(encoding="utf-8"))

    @fastapi_app.get("/runs/{run_id}/mapping", response_class=PlainTextResponse)
    def runs_mapping(run_id: str, company_id: str | None = None):
        runs_dir = (runs_root / company_id) if company_id else runs_root
        path = runs_dir / f"{run_id}.mapping.md"
        if not path.exists():
            raise HTTPException(status_code=404, detail="mapping manifest not found for run_id")
        return PlainTextResponse(path.read_text(encoding="utf-8"))

    @fastapi_app.get("/download/{run_id}/{key}", response_class=FileResponse)
    def download_artifact(run_id: str, key: str, company_id: str | None = None):
        """
        Download an artifact produced by a run.
        Safety: only serves files listed in the run JSON outputs mapping.
        """
        uploads_p = Path(uploads_dir)
        runs_dir = (runs_root / company_id) if company_id else runs_root
        run_json = runs_dir / f"{run_id}.json"
        if not run_json.exists():
            raise HTTPException(status_code=404, detail="run json not found")
        try:
            import json

            run = json.loads(run_json.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail="failed to read run json") from exc

        outputs = (run.get("outputs") or {})
        if key not in outputs:
            raise HTTPException(status_code=404, detail="artifact key not found for run")
        path = Path(outputs[key])
        if not path.exists():
            raise HTTPException(status_code=404, detail="artifact file missing on disk")

        # Restrict served files to known safe roots
        safe_roots = [
            uploads_p.resolve(),
            (uploads_p / "companies").resolve(),
        ]
        try:
            resolved = path.resolve()
            if not any(str(resolved).startswith(str(root) + "/") or resolved == root for root in safe_roots):
                raise HTTPException(status_code=400, detail="artifact path not allowed")
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="artifact path invalid") from exc

        return FileResponse(
            path,
            filename=path.name,
            media_type="application/octet-stream",
        )

    return fastapi_app


app = create_app(_default_uploads_dir())

