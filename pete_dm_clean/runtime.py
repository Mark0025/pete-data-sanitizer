from __future__ import annotations

import json
import sys
import time
from collections import Counter
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional


def utc_ts() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class StepRecord:
    name: str
    status: str = "running"  # running|ok|warn|fail
    started_at: str = field(default_factory=utc_ts)
    ended_at: Optional[str] = None
    duration_ms: Optional[int] = None
    metrics: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class RunRecord:
    run_id: str
    created_at: str
    app_version: str
    inputs: dict[str, str]
    outputs: dict[str, str] = field(default_factory=dict)
    steps: list[StepRecord] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


class RunTracker:
    def __init__(self, *, runs_dir: Path, app_version: str, inputs: dict[str, str]):
        self.runs_dir = Path(runs_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
        self.record = RunRecord(
            run_id=self.run_id,
            created_at=utc_ts(),
            app_version=app_version,
            inputs=inputs,
        )
        self._call_trace_stop: Optional[Callable[[], None]] = None
        self._call_counts: Counter[str] | None = None
        self._call_sequence_path: Path | None = None
        self._call_counts_path: Path | None = None

    def step(self, name: str) -> "_StepCtx":
        return _StepCtx(self, name)

    def set_output(self, key: str, path: Path):
        self.record.outputs[key] = str(path)

    def set_summary(self, **kwargs: Any):
        self.record.summary.update(kwargs)

    @property
    def json_path(self) -> Path:
        return self.runs_dir / f"{self.run_id}.json"

    @property
    def summary_md_path(self) -> Path:
        return self.runs_dir / f"{self.run_id}.summary.md"

    @property
    def call_sequence_path(self) -> Path:
        return self.runs_dir / f"{self.run_id}.calls.txt"

    @property
    def call_counts_path(self) -> Path:
        return self.runs_dir / f"{self.run_id}.call_counts.json"

    @property
    def log_path(self) -> Path:
        return self.runs_dir / f"{self.run_id}.log"

    @property
    def debug_json_path(self) -> Path:
        return self.runs_dir / f"{self.run_id}.debug.json"

    @property
    def debug_md_path(self) -> Path:
        return self.runs_dir / f"{self.run_id}.debug.md"

    def start_call_trace(
        self,
        *,
        project_root: Path,
        max_events: int = 50_000,
        include_stdlib: bool = False,
    ) -> None:
        """
        Learning mode: record function calls during runtime.

        - Writes a sequential call log to `<run_id>.calls.txt` (up to max_events)
        - Writes aggregate counts to `<run_id>.call_counts.json`

        NOTE: This is intentionally OFF by default. It can be noisy and slower.
        """
        if self._call_trace_stop is not None:
            return

        root = Path(project_root).resolve()
        seq_path = self.call_sequence_path
        counts_path = self.call_counts_path
        counts: Counter[str] = Counter()

        # open file once for speed
        f = seq_path.open("w", encoding="utf-8")
        f.write(f"# run_id={self.run_id} created_at={self.record.created_at}\n")
        f.write(f"# max_events={max_events} include_stdlib={include_stdlib}\n")

        state = {"n": 0, "stopped": False}

        def should_include(filename: str | None) -> bool:
            if filename is None:
                return False
            try:
                p = Path(filename).resolve()
            except Exception:
                return False
            if include_stdlib:
                return True
            return root in p.parents or p == root

        def fmt(frame) -> str:
            code = frame.f_code
            fn = code.co_name
            mod = frame.f_globals.get("__name__", "")
            return f"{mod}:{fn}"

        def profiler(frame, event, arg):
            if state["stopped"]:
                return
            if event != "call":
                return profiler

            filename = frame.f_code.co_filename
            if not should_include(filename):
                return profiler

            state["n"] += 1
            key = fmt(frame)
            counts[key] += 1

            if state["n"] <= max_events:
                f.write(f"{state['n']:06d} {key} ({filename}:{frame.f_code.co_firstlineno})\n")
            elif state["n"] == max_events + 1:
                f.write(f"... truncated after {max_events} call events ...\n")

            if state["n"] >= max_events + 1:
                # keep counting, but stop writing sequence for performance
                pass
            return profiler

        sys.setprofile(profiler)

        def stop():
            if state["stopped"]:
                return
            state["stopped"] = True
            sys.setprofile(None)
            f.flush()
            f.close()
            counts_path.write_text(json.dumps(counts.most_common(), indent=2), encoding="utf-8")
            self._call_counts = counts
            self._call_sequence_path = seq_path
            self._call_counts_path = counts_path

        self._call_trace_stop = stop

    def stop_call_trace(self) -> None:
        if self._call_trace_stop is None:
            return
        self._call_trace_stop()
        self._call_trace_stop = None

    def write(self):
        self.json_path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        self.summary_md_path.write_text(self.to_markdown(), encoding="utf-8")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.record.run_id,
            "created_at": self.record.created_at,
            "app_version": self.record.app_version,
            "inputs": self.record.inputs,
            "outputs": self.record.outputs,
            "summary": self.record.summary,
            "call_trace": {
                "sequence_path": str(self._call_sequence_path) if self._call_sequence_path else None,
                "counts_path": str(self._call_counts_path) if self._call_counts_path else None,
            },
            "steps": [
                {
                    "name": s.name,
                    "status": s.status,
                    "started_at": s.started_at,
                    "ended_at": s.ended_at,
                    "duration_ms": s.duration_ms,
                    "metrics": s.metrics,
                    "error": s.error,
                }
                for s in self.record.steps
            ],
        }

    def to_markdown(self) -> str:
        r = self.record
        lines: list[str] = []
        lines.append("## Runtime run summary")
        lines.append("")
        lines.append(f"- **run_id**: `{r.run_id}`")
        lines.append(f"- **created_at**: {r.created_at}")
        lines.append(f"- **app_version**: {r.app_version}")
        lines.append("")
        lines.append("### Inputs")
        lines.append("")
        for k, v in r.inputs.items():
            lines.append(f"- **{k}**: `{v}`")
        lines.append("")
        lines.append("### Outputs")
        lines.append("")
        for k, v in r.outputs.items():
            lines.append(f"- **{k}**: `{v}`")
        lines.append("")
        if r.summary:
            lines.append("### Key metrics")
            lines.append("")
            for k, v in r.summary.items():
                lines.append(f"- **{k}**: {v}")
            lines.append("")
        lines.append("### Steps")
        lines.append("")
        for s in r.steps:
            lines.append(f"- **{s.name}**: {s.status} ({s.duration_ms}ms)")
            if s.metrics:
                for mk, mv in s.metrics.items():
                    lines.append(f"  - {mk}: {mv}")
            if s.error:
                lines.append(f"  - error: {s.error}")
        lines.append("")
        return "\n".join(lines)


class _StepCtx:
    def __init__(self, tracker: RunTracker, name: str):
        self.tracker = tracker
        self.step = StepRecord(name=name)
        self._t0 = time.perf_counter()
        self.tracker.record.steps.append(self.step)

    def metric(self, **kwargs: Any) -> None:
        self.step.metrics.update(kwargs)

    def ok(self) -> None:
        self.step.status = "ok"

    def warn(self) -> None:
        self.step.status = "warn"

    def fail(self, err: str) -> None:
        self.step.status = "fail"
        self.step.error = err

    def __enter__(self) -> "_StepCtx":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.step.ended_at = utc_ts()
        self.step.duration_ms = int((time.perf_counter() - self._t0) * 1000)
        if exc is not None:
            self.fail(str(exc))
            # don't swallow exceptions
            return False
        if self.step.status == "running":
            self.ok()
        return False


_CURRENT_TRACKER: ContextVar[RunTracker | None] = ContextVar("_CURRENT_TRACKER", default=None)


def set_tracker(tracker: RunTracker | None) -> None:
    """
    Optional convenience for large codebases: store the current run tracker in context,
    so deeper modules can call get_tracker() without threading the tracker through every
    function signature.
    """
    _CURRENT_TRACKER.set(tracker)


def get_tracker() -> RunTracker | None:
    return _CURRENT_TRACKER.get()

