from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import Any


@dataclass(slots=True)
class ActionTimer:
    started_at: str
    started_perf: float


@dataclass(slots=True)
class ActionResult:
    # started_at/finished_at describe the action execution window. The separate
    # StateRecord.timestamp describes when the result was persisted locally.
    action: str
    plugin_id: str
    ok: bool
    detail: str
    returncode: int
    stdout: str
    stderr: str
    started_at: str
    finished_at: str
    duration_ms: int
    metadata: dict[str, Any] = field(default_factory=dict)


def start_action() -> ActionTimer:
    return ActionTimer(
        started_at=datetime.now(timezone.utc).isoformat(),
        started_perf=perf_counter(),
    )


def finish_action(
    timer: ActionTimer,
    *,
    action: str,
    plugin_id: str,
    ok: bool,
    detail: str,
    returncode: int,
    stdout: str = "",
    stderr: str = "",
    metadata: dict[str, Any] | None = None,
) -> ActionResult:
    return ActionResult(
        action=action,
        plugin_id=plugin_id,
        ok=ok,
        detail=detail,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        started_at=timer.started_at,
        finished_at=datetime.now(timezone.utc).isoformat(),
        duration_ms=int((perf_counter() - timer.started_perf) * 1000),
        metadata=metadata or {},
    )
