from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def _write_min_template(path: Path) -> None:
    # Minimal Pete import template columns needed for the pipeline to behave normally.
    cols = [
        "External Id",
        "Full Address",
        "Property Street",
        "Property City",
        "Property State",
        "Property ZIP",
        "Status",
        "Campaign",
        "Phase",
        "Seller",
        "Seller2",
        "Seller3",
        "Tags",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=cols).to_excel(path, index=False)


def _write_contacts_csv(path: Path) -> None:
    # Contacts-only mode requires associated_property_address_full.
    rows = [
        {
            "associated_property_address_full": "4708 Ashland Ct, Kansas City, MO 64127",
            "first_name": "A",
            "last_name": "Owner",
            "contact_flags": "Likely Owner",
            "email_address_1": "a@example.com",
            "phone_1": "555-111-2222",
        },
        {
            "associated_property_address_full": "4708 Ashland Ct, Kansas City, MO 64127",
            "first_name": "B",
            "last_name": "Person",
            "contact_flags": "",
            "email_address_1": "b@example.com",
            "phone_1": "555-111-3333",
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def test_web_ui_build_contacts_only_randomize_external_ids(tmp_path: Path) -> None:
    """
    Integration smoke test:
    - start FastAPI app (create_app)
    - run UI build in contacts-only mode
    - ensure outputs exist
    - ensure External Ids are randomized when the UI flag is set
    """
    from fastapi.testclient import TestClient

    from pete_dm_clean.server import create_app

    uploads_dir = tmp_path / "uploads"
    (uploads_dir / "runs").mkdir(parents=True, exist_ok=True)
    _write_min_template(uploads_dir / "templates" / "Properties Template (15).xlsx")
    _write_contacts_csv(uploads_dir / "contacts.csv")

    app = create_app(uploads_dir=uploads_dir)
    client = TestClient(app)

    resp = client.post(
        "/ui/build",
        data={
            "company_id": "",
            "contacts_only": "true",
            "desired_outcome": "",
            "contacts": "contacts.csv",
            "template": "",
            "export_prefix": "TEST.PETE",
            "export_date_format": "%m.%d.%y",
            "max_sellers": "3",
            "randomize_external_ids": "true",
            "external_id_seed": "123",
            "external_id_digits": "8",
            "debug_report": "",
            "no_desktop_copy": "true",
        },
    )
    assert resp.status_code == 200
    assert "Build complete" in resp.text

    # Locate the latest run json and verify output csv has randomized external ids.
    runs_dir = uploads_dir / "runs"
    run_jsons = sorted(runs_dir.glob("*.json"))
    assert run_jsons, "expected a run json to be written"
    run = json.loads(run_jsons[-1].read_text(encoding="utf-8"))
    out_csv = Path((run.get("outputs") or {}).get("out_csv") or "")
    assert out_csv.exists(), f"expected output CSV to exist at {out_csv}"

    df = pd.read_csv(out_csv)
    assert "External Id" in df.columns
    ids = [str(x) for x in df["External Id"].tolist()]
    assert all(i.isdigit() and len(i) == 8 for i in ids)
    assert len(set(ids)) == len(ids)

