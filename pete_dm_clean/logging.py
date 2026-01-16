from __future__ import annotations

from pathlib import Path
from typing import Optional

from loguru import logger


def configure_logging(*, log_file: Optional[Path] = None) -> None:
    """
    Configure Loguru once for this process.

    - Keeps stderr logging.
    - Optionally writes to a file (append).
    """
    # Avoid duplicate handlers if configure is called multiple times.
    logger.remove()
    logger.add(lambda msg: print(msg, end=""))  # stderr-like, but consistent in envs

    if log_file is not None:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            str(log_file),
            rotation=None,
            retention=None,
            enqueue=False,
            backtrace=True,
            diagnose=False,
        )


def get_logger():
    return logger

