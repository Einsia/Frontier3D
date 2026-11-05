"""L1 monotonic wall-clock budgets; children may shorten but never renew them."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any


class BudgetExhausted(RuntimeError):
    """No new work is allowed; cleanup and evidence persistence remain allowed."""


def positive_seconds(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a positive finite number")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return float(value)


@dataclass(frozen=True)
class DeadlineBudget:
    started: float
    deadline: float
    configured_seconds: float
    inherited_deadline: float | None

    @classmethod
    def start(
        cls, seconds: float, *, deadline: float | None = None,
        started: float | None = None,
    ) -> DeadlineBudget:
        seconds = positive_seconds(seconds, "budget seconds")
        if deadline is not None and (
            isinstance(deadline, bool) or not isinstance(deadline, (int, float))
            or not math.isfinite(deadline)
        ):
            raise ValueError("deadline must be a finite monotonic timestamp")
        started = time.monotonic() if started is None else started
        local_deadline = started + seconds
        return cls(
            started, min(local_deadline, deadline) if deadline is not None else local_deadline,
            seconds, deadline,
        )

    @property
    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    @property
    def exhausted(self) -> bool:
        return time.monotonic() >= self.deadline

    def allowance(self, timeout: float) -> float:
        return min(positive_seconds(timeout, "timeout"), self.remaining)

    def check(self) -> None:
        if self.exhausted:
            raise BudgetExhausted("L1 shared wall-clock budget exhausted")

    def record(self, scope: str) -> dict[str, Any]:
        now = time.monotonic()
        return {
            "protocol": "l1-deadline-v1", "scope": scope,
            "configured_seconds": self.configured_seconds,
            "deadline_monotonic": self.deadline,
            "inherited_deadline_monotonic": self.inherited_deadline,
            "elapsed_seconds": max(0.0, now - self.started),
            "remaining_seconds": max(0.0, self.deadline - now),
            "overrun_seconds": max(0.0, now - self.deadline),
            "exhausted": now >= self.deadline,
            "clock_scope": "same_host_monotonic_not_a_resume_token",
            "after_deadline": "cleanup_and_evidence_only",
        }
