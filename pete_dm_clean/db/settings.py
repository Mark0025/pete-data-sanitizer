from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DbSettings:
    enabled: bool
    url: str


def _truthy(s: str) -> bool:
    return s.strip().lower() in {"1", "true", "yes", "y", "on"}


def default_db_path_from_uploads(uploads_dir: Path) -> Path:
    """
    Keep the DB adjacent to uploads for container volumes:

      /data/uploads  -> /data/pete_dm_clean.sqlite
      ./uploads      -> ./uploads/pete_dm_clean.sqlite (local default if enabled)
    """
    uploads_dir = Path(uploads_dir)
    parent = uploads_dir.parent if uploads_dir.parent != Path("") else Path(".")
    # Prefer parent (so DB isn't buried in uploads/), but if uploads is relative,
    # store alongside it for convenience.
    if uploads_dir.is_absolute():
        return parent / "pete_dm_clean.sqlite"
    return uploads_dir / "pete_dm_clean.sqlite"


def resolve_db_settings(*, uploads_dir: Path) -> DbSettings:
    """
    DB is opt-in: enable by setting DB_URL or DB_PATH or DB_ENABLED=1.

    - DB_URL: full SQLAlchemy URL (e.g., sqlite:////data/pete_dm_clean.sqlite, postgresql+psycopg://...)
    - DB_PATH: filesystem path to SQLite db file
    - DB_ENABLED: if true, uses default path derived from uploads_dir
    """
    env_url = (os.getenv("DB_URL") or "").strip()
    env_path = (os.getenv("DB_PATH") or "").strip()
    env_enabled = (os.getenv("DB_ENABLED") or "").strip()

    if env_url:
        return DbSettings(enabled=True, url=env_url)

    if env_path:
        p = Path(env_path).expanduser()
        # sqlite absolute path uses 4 slashes: sqlite:////abs/path
        if p.is_absolute():
            return DbSettings(enabled=True, url=f"sqlite:////{p.as_posix().lstrip('/')}")
        return DbSettings(enabled=True, url=f"sqlite:///{p.as_posix()}")

    if env_enabled and _truthy(env_enabled):
        p = default_db_path_from_uploads(Path(uploads_dir))
        if p.is_absolute():
            return DbSettings(enabled=True, url=f"sqlite:////{p.as_posix().lstrip('/')}")
        return DbSettings(enabled=True, url=f"sqlite:///{p.as_posix()}")

    return DbSettings(enabled=False, url="")

