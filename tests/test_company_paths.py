from __future__ import annotations

from pathlib import Path

from pete_dm_clean.companies import company_paths


def test_company_paths_layout():
    uploads = Path("uploads")
    cid = "00000000-0000-0000-0000-000000000000"
    p = company_paths(uploads_dir=uploads, company_id=cid)
    assert str(p.inputs_dir).endswith(f"uploads/companies/{cid}/inputs")
    assert str(p.outputs_dir).endswith(f"uploads/companies/{cid}/outputs")
    assert str(p.runs_dir).endswith(f"uploads/runs/{cid}")
    assert str(p.flowcharts_dir).endswith(f"uploads/flowcharts/{cid}")

