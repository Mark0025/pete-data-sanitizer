from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure repo root is on sys.path for tests when running via `uv run pytest`.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")


def _init_loguru_sink() -> Path | None:
    """
    Write a concise pytest run log to disk (Loguru), so we don't spam console/chat.
    """
    try:
        from loguru import logger  # type: ignore
    except Exception:
        return None

    log_dir = ROOT / "uploads" / "runs" / "_tests"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"pytest_{_utc_stamp()}.log"
    latest_path = log_dir / "pytest_latest.loguru.log"

    # Keep it small and useful.
    logger.remove()
    logger.add(
        str(log_path),
        level="INFO",
        enqueue=True,
        backtrace=False,
        diagnose=False,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {message}",
    )
    # Also write a stable "latest" file for convenience.
    logger.add(
        str(latest_path),
        level="INFO",
        enqueue=True,
        backtrace=False,
        diagnose=False,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {message}",
    )
    logger.info("pytest_start cwd={} root={}", str(Path.cwd()), str(ROOT))
    return log_path


_PYTEST_LOG_PATH = _init_loguru_sink()


def pytest_runtest_logreport(report: Any) -> None:
    """
    Log each test outcome once (on call phase).
    """
    if _PYTEST_LOG_PATH is None:
        return
    if getattr(report, "when", "") != "call":
        return
    try:
        from loguru import logger  # type: ignore
    except Exception:
        return

    nodeid = getattr(report, "nodeid", "unknown")
    duration = float(getattr(report, "duration", 0.0) or 0.0)
    outcome = getattr(report, "outcome", "unknown")
    if outcome == "passed":
        logger.info("PASS {:.3f}s {}", duration, nodeid)
    elif outcome == "skipped":
        logger.info("SKIP {:.3f}s {}", duration, nodeid)
    else:
        logger.warning("FAIL {:.3f}s {}", duration, nodeid)

def pytest_collection_finish(session: Any) -> None:
    """
    Log collected tests (bounded) so you can see exactly what ran.
    """
    if _PYTEST_LOG_PATH is None:
        return
    try:
        from loguru import logger  # type: ignore
    except Exception:
        return

    try:
        items = list(getattr(session, "items", []) or [])
        nodeids = [getattr(i, "nodeid", "unknown") for i in items]
        max_list = 200
        logger.info("pytest_collected count={}", len(nodeids))
        for nid in nodeids[:max_list]:
            logger.info("COLLECT {}", nid)
        if len(nodeids) > max_list:
            logger.info("COLLECT_TRUNCATED total={} shown={}", len(nodeids), max_list)
    except Exception:
        # best-effort logging only
        pass


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    if _PYTEST_LOG_PATH is None:
        return
    try:
        from loguru import logger  # type: ignore
    except Exception:
        return

    logger.info("pytest_finish exitstatus={} log_path={}", exitstatus, str(_PYTEST_LOG_PATH))

