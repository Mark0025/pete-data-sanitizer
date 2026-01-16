from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

import pandas as pd

from pete_dm_clean.template_inherit import ensure_template_shape, load_template_columns

F = TypeVar("F", bound=Callable[..., pd.DataFrame])


@dataclass(frozen=True)
class GeneratorSpec:
    """
    Declarative metadata for a “generator” (pipeline output builder).

    This stays pure-Python and is intentionally UI-agnostic.
    """

    name: str
    template_default: Path
    description: str = ""


GENERATOR_REGISTRY: dict[str, GeneratorSpec] = {}


def pete_template_generator(
    *,
    name: str,
    template_default: Path,
    description: str = "",
    template_path_kw: str = "template_path",
    drop_extra_columns: bool = True,
) -> Callable[[F], F]:
    """
    Decorator for generator functions that output Pete-template-shaped DataFrames.

    Contract:
    - The decorated function must accept a keyword argument named `template_columns`.
    - Callers pass `template_path=...` (optional). If omitted, `template_default` is used.
    - The wrapper loads template columns, calls the function, then enforces shape.
    """

    def decorator(fn: F) -> F:
        spec = GeneratorSpec(name=name, template_default=Path(template_default), description=description)
        GENERATOR_REGISTRY[name] = spec

        def wrapped(*args: Any, **kwargs: Any) -> pd.DataFrame:
            template_path = Path(kwargs.pop(template_path_kw, spec.template_default))
            template_cols = load_template_columns(template_path)
            kwargs["template_columns"] = template_cols
            df = fn(*args, **kwargs)
            return ensure_template_shape(df, template_cols, drop_extra=drop_extra_columns)

        # type: ignore[return-value]
        return wrapped  # pyright/mypy: we preserve callable shape for runtime

    return decorator

