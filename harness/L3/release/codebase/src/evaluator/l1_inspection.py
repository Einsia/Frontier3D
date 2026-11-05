"""L1 inspection deadline attribution, child cleanup and file-I/O evidence.

Directory preparation, log persistence and default metadata persistence are
isolated workers.  Process launch setup and parent-side encoding remain
cooperative until G07-B1 is complete.
This is not a blanket hard-I/O or security guarantee.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

from .l1_budget import DeadlineBudget
from .l1_failures import InspectionFailure
from .l1_file_io import run_file_io
from .l1_log_io import LogSink
from .l1_parent_io import ensure_directory
from .l1_persistence import JsonPersistence
from .l1_result import read_result

MISSING = object()
CLEANUP_SECONDS = 2.0


class InspectionSession:
    def __init__(self, directory, timeout, deadline, persist=None):
        self.directory, self.persist = directory, persist
        self.budget = DeadlineBudget.start(timeout, deadline=deadline)
        self.shared_deadline = deadline
        self.persistence = JsonPersistence(self.budget.deadline)
        self.path = directory / "inspector_record.json"
        self.record = {
            "protocol": "l1-inspector-execution-v1",
            "status": "not_started",
            "pid": None,
            "deadline_monotonic": self.budget.deadline,
            "shared_deadline_monotonic": deadline,
            "cleanup_limit_seconds": CLEANUP_SECONDS,
            "input_io": {},
            "json_io": {},
            "path_io": [],
            "record_persisted": False,
            "remaining_parent_io": ["paths", "launch_setup", "logs"]
            + (["injected_metadata_callback"] if persist is not None else []),
            "metadata_acknowledgement": "inspector_persistence_return_value_not_file_presence",
        }

    def timeout(self):
        shared = (
            self.shared_deadline is not None
            and time.monotonic() >= self.shared_deadline
        )
        return InspectionFailure(
            "infrastructure_error",
            "EVALUATION_BUDGET_EXHAUSTED" if shared else "INSPECTION_TIMEOUT",
            "Inspection stage exhausted its inherited or local deadline",
        )

    def guard(self):
        if self.budget.exhausted:
            raise self.timeout()

    def evidence(self):
        return {**self.record, "record_path": str(self.path)}

    def _terminal(self, failure):
        if failure is None:
            self.record["status"] = "completed"
        else:
            interrupted = isinstance(failure, (KeyboardInterrupt, SystemExit))
            code = getattr(failure, "code", type(failure).__name__)
            self.record["status"] = (
                "interrupted"
                if interrupted
                else "budget_exhausted"
                if code in {"INSPECTION_TIMEOUT", "EVALUATION_BUDGET_EXHAUSTED"}
                else "failed"
            )
            self.record["failure"] = {
                "status": getattr(failure, "status", "infrastructure_error"),
                "code": code,
            }
        self.record["budget"] = self.budget.record("inspection")

    def __enter__(self):
        try:
            self.guard()
        except InspectionFailure as error:
            self._terminal(error)
            error.inspector_execution = self.evidence()
            raise
        try:
            prepared = ensure_directory(self.directory, deadline=self.budget.deadline, parents=True)
            self.record["path_io"].append(prepared["execution"])
        except (InspectionFailure, OSError, ValueError, TypeError, KeyboardInterrupt, SystemExit) as error:
            failure = error if isinstance(error, (InspectionFailure, KeyboardInterrupt, SystemExit)) else InspectionFailure(
                "infrastructure_error", "INSPECTION_PATH_IO_ERROR", type(error).__name__
            )
            self._terminal(failure)
            failure.inspector_execution = self.evidence()
            failure.inspector_persistence = self.persistence.evidence()
            raise failure
        return self

    def __exit__(self, error_type, error, traceback):
        failure = error
        if failure is None:
            try:
                self.guard()
            except InspectionFailure as expired:
                failure = expired
        self._terminal(failure)
        try:
            self._store(cleanup=failure is not None)
        except (
            OSError,
            ValueError,
            TypeError,
            InspectionFailure,
            KeyboardInterrupt,
            SystemExit,
        ) as persistence:
            self.record["persistence_error"] = type(persistence).__name__
            if failure is None:
                failure = (
                    persistence
                    if isinstance(persistence, (KeyboardInterrupt, SystemExit))
                    else self.timeout()
                    if isinstance(persistence, InspectionFailure)
                    and persistence.code == "EVALUATION_BUDGET_EXHAUSTED"
                    else InspectionFailure(
                        "infrastructure_error",
                        "INSPECTION_RECORD_ERROR",
                        type(persistence).__name__,
                    )
                )
            self._terminal(failure)
        if failure is None:
            try:
                self.guard()
            except InspectionFailure as expired:
                failure = expired
        if failure is not None and error is None:
            # A late/failed normal commit may already have installed bytes.
            # Try to replace them with failure evidence, using ONE cleanup
            # allowance. No receipt/file alone makes a late operation valid.
            self._terminal(failure)
            try:
                self._store(cleanup=True)
            except (OSError, ValueError, TypeError, InspectionFailure) as persistence:
                self.record["persistence_error"] = type(persistence).__name__
        if failure is not None:
            failure.inspector_execution = self.evidence()
            failure.inspector_persistence = self.persistence.evidence()
            if failure is not error:
                raise failure
        return False

    def _store(self, *, cleanup):
        self.record["record_persisted"] = True
        try:
            if self.persist is None:
                self.persistence.write(self.path, self.record, cleanup=cleanup)
            else:
                self.persist(self.path, self.record)
        except BaseException:
            self.record["record_persisted"] = False
            raise

    def hash(self, path: Path, phase: str, name: str):
        self.guard()
        directory = self.directory / "input_io" / phase / name
        slot = {"path": str(path), "directory": str(directory), "status": "started"}
        self.record["input_io"].setdefault(phase, {})[name] = slot
        try:
            result = run_file_io(
                "hash",
                {"path": str(path)},
                output=directory,
                deadline=self.budget.deadline,
            )
        except (
            InspectionFailure,
            OSError,
            ValueError,
            KeyboardInterrupt,
            SystemExit,
        ) as error:
            slot.update(status="failed", error_type=type(error).__name__)
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            if isinstance(error, InspectionFailure):
                if error.code == "EVALUATION_BUDGET_EXHAUSTED":
                    raise self.timeout() from error
                raise
            raise InspectionFailure(
                "infrastructure_error",
                "INSPECTION_INPUT_IO_ERROR",
                type(error).__name__,
            ) from error
        slot.update(status="completed", result=result)
        self.guard()
        return result["sha256"]

    def read_json(self, name: str, *, optional=False, limit=256 * 1024 * 1024):
        self.guard()
        try:
            value, reception = read_result(
                self.directory / name, deadline=self.budget.deadline, max_bytes=limit
            )
        except (InspectionFailure, KeyboardInterrupt, SystemExit) as error:
            reception = getattr(error, "result_reception", None)
            self.record["json_io"][name] = reception
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            if error.code == "EVALUATION_BUDGET_EXHAUSTED":
                raise self.timeout() from error
            if (
                optional
                and reception
                and (reception.get("reader_result") or {}).get("error_type")
                == "FileNotFoundError"
            ):
                return MISSING
            raise InspectionFailure(
                "infrastructure_error", "WORKER_PROTOCOL_ERROR", error.reason
            ) from error
        self.record["json_io"][name] = reception
        self.guard()
        return value

    def launch(self, command, environment):
        self.guard()
        self.record["command"] = command
        log_sink = LogSink(self.directory / "inspect.log", self.budget.deadline)
        log_stream = None
        process = None
        failure = None
        returncode = None
        try:
            log_stream = log_sink.start()
            self.guard()
            # No Popen context manager: its implicit wait has no timeout.
            process = subprocess.Popen(
                command,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=environment,
                start_new_session=True,
            )
            self.record.update(
                status="running", pid=process.pid, process_group=process.pid
            )
            log_stream.close()
            returncode = process.wait(timeout=self.budget.remaining)
        except subprocess.TimeoutExpired as error:
            failure = self.timeout()
            failure.__cause__ = error
        except BaseException as error:  # noqa: BLE001 -- cleanup, then rethrow original including cancellation
            failure = error
        finally:
            if log_stream is not None:
                log_stream.close()
            started = time.monotonic()
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                    self.record["group_kill_sent"] = True
                except ProcessLookupError:
                    self.record["group_kill_sent"] = True
                except OSError as error:
                    self.record.update(
                        group_kill_sent=False, cleanup_error=type(error).__name__
                    )
                try:
                    process.wait(timeout=CLEANUP_SECONDS)
                    self.record["leader_reaped"] = True
                except subprocess.TimeoutExpired:
                    self.record["leader_reaped"] = False
                except BaseException as error:  # noqa: BLE001 -- preserve initiating exception through cleanup
                    self.record.update(leader_reaped=False, cleanup_error=type(error).__name__)
                    failure = failure or error
                self.record["return_code"] = process.returncode
            else:
                self.record["launch_failure"] = {
                    "status": "not_started", "pid": None,
                    "exception_type": type(failure).__name__ if failure else None,
                }
            self.record["cleanup_seconds"] = time.monotonic() - started
            try:
                # Always finish a started log writer, including Popen errors
                # before an inspector PID exists. Never replace a cancellation
                # with the secondary error of collecting its log.
                self.record["log_io"] = log_sink.finish(
                    cleanup=failure is not None or self.record.get("return_code") != 0 or self.budget.exhausted
                )
            except BaseException as error:  # noqa: BLE001 -- log cleanup must not mask original cancellation
                self.record["log_io"] = {**log_sink.execution, "collection_error": type(error).__name__}
                failure = failure or error
            if failure is None and self.record["log_io"].get("status") != "completed":
                failure = InspectionFailure(
                    "infrastructure_error", "INSPECTION_LOG_IO_ERROR",
                    "Inspector log was not durably acknowledged",
                )
        if failure is not None:
            if process is None and isinstance(failure, OSError):
                raise InspectionFailure("infrastructure_error", "WORKER_LAUNCH_ERROR",
                                        type(failure).__name__) from failure
            raise failure
        if not self.record.get("leader_reaped") or not self.record.get("group_kill_sent"):
            raise InspectionFailure(
                "infrastructure_error",
                "INSPECTION_CLEANUP_TIMEOUT",
                "Inspector group cleanup incomplete",
            )
        self.guard()
        return returncode
