"""
Database layer (metadata only).

This package intentionally stores only *small metadata* (runs, companies, artifact paths).
Large artifacts (CSV/XLSX/flowcharts/logs) stay on disk in the mounted volume.
"""

from __future__ import annotations

from pete_dm_clean.db.ingest import maybe_ingest_run_json
from pete_dm_clean.db.session import init_db_if_enabled

__all__ = ["init_db_if_enabled", "maybe_ingest_run_json"]

