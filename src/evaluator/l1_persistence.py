"""Bounded atomic L1 JSON persistence and a non-renewable failure allowance.

Encoding is cooperative; open/write/fsync/replace are in an exec worker. The
caller must use trusted metadata paths. This is neither a filesystem sandbox
nor an all-Python hard deadline. An unacknowledged file is not a success receipt.
"""

from __future__ import annotations

import time
from pathlib import Path

from .l1_budget import DeadlineBudget
from .l1_failures import InspectionFailure
from .l1_request import prepare_request

MAX_JSON_BYTES = 64 * 1024 * 1024
CLEANUP_SECONDS = 2.0
REAP_RESERVE_SECONDS = 0.25


class JsonPersistence:
    """Reuse one instance for all writes in the same cleanup scope."""

    def __init__(self, deadline: float):
        DeadlineBudget.start(1.0, deadline=deadline)
        self.deadline = deadline
        self.cleanup_deadline = None
        self.records = []

    def begin_cleanup(self):
        if self.cleanup_deadline is None:
            self.cleanup_deadline = (
                min(time.monotonic(), self.deadline) + CLEANUP_SECONDS
            )
        return self.cleanup_deadline

    def cleanup_transaction(self):
        """Separate ACK ledger, SAME failure allowance as its owning caller."""
        transaction = JsonPersistence(self.deadline)
        transaction.cleanup_deadline = self.begin_cleanup()
        return transaction

    def write(self, path: Path, value, *, cleanup=False, replace=True):
        if type(cleanup) is not bool:
            raise ValueError("Explicit boolean cleanup mode required")
        if type(replace) is not bool:
            raise ValueError("Explicit boolean replacement policy required")
        if cleanup:
            end = self.begin_cleanup()
            deadline = end - REAP_RESERVE_SECONDS
        else:
            if self.cleanup_deadline is not None:
                raise InspectionFailure(
                    "infrastructure_error",
                    "PERSISTENCE_AFTER_CLEANUP",
                    "Normal work cannot resume after failure persistence",
                )
            deadline, end = self.deadline, self.deadline + CLEANUP_SECONDS
        row = {
            "protocol": "l1-json-persistence-v1",
            "path": str(path),
            "scope": "failure_cleanup" if cleanup else "evaluation",
            "evaluation_deadline_monotonic": self.deadline,
            "deadline_monotonic": deadline,
            "cleanup_deadline_monotonic": end,
            "status": "not_started",
            "execution": None,
            "commit_mode": "replace_regular" if replace else "create_only",
        }
        self.records.append(row)
        if not cleanup and time.monotonic() >= self.deadline:
            row["status"] = "budget_exhausted"
            row["execution"] = {
                "protocol": "l1-request-preparation-execution-v1",
                "status": "budget_exhausted",
                "pid": None,
                "deadline_monotonic": deadline,
                "cleanup_deadline_monotonic": end,
            }
            raise InspectionFailure(
                "infrastructure_error", "EVALUATION_BUDGET_EXHAUSTED",
                "No persistence writer after shared deadline",
            )
        try:
            execution = prepare_request(
                path,
                value,
                deadline=deadline,
                max_bytes=MAX_JSON_BYTES,
                replace=replace,
                cleanup_deadline=end,
            )
        except (InspectionFailure, KeyboardInterrupt, SystemExit) as error:
            row["execution"] = getattr(error, "request_preparation", None)
            row["status"] = (row["execution"] or {}).get("status", "failed")
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                error.json_persistence = row
                raise
            code = (
                (
                    "PERSISTENCE_CLEANUP_EXHAUSTED"
                    if cleanup
                    else "EVALUATION_BUDGET_EXHAUSTED"
                )
                if error.code == "EVALUATION_BUDGET_EXHAUSTED"
                else (
                    "JSON_PERSISTENCE_LIMIT"
                    if error.code == "COMPUTE_INPUT_LIMIT"
                    else "JSON_PERSISTENCE_FAILED"
                )
            )
            failure = InspectionFailure("infrastructure_error", code, error.reason)
            failure.json_persistence = row
            raise failure from error
        row.update(
            status="completed",
            execution=execution,
            sha256=execution["request_sha256"],
            bytes=execution["bytes"],
        )
        return row

    def evidence(self):
        return {
            "protocol": "l1-json-persistence-session-v1",
            "deadline_monotonic": self.deadline,
            "cleanup_deadline_monotonic": self.cleanup_deadline,
            "cleanup_seconds": CLEANUP_SECONDS,
            "reap_reserve_seconds": REAP_RESERVE_SECONDS,
            "records": list(self.records),
        }
