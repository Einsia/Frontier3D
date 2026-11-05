"""Blender-side entry point used by :mod:`src.render.cli`.

This file is executed by Blender, not by the project's virtual environment.
The generated script is deliberately executed as ``__main__`` so scripts that
use a normal ``if __name__ == '__main__'`` guard work as expected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import traceback
from pathlib import Path

import bpy

_RNG_FUNCTIONS = (
    "random",
    "randint",
    "randrange",
    "choice",
    "choices",
    "sample",
    "shuffle",
    "uniform",
    "getrandbits",
    "seed",
)


def _state_digest(value: object) -> str:
    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()


def _install_rng_trace() -> callable:
    """Trace module and common explicit RNG calls made by the candidate script.

    This is an evaluator-owned reproducibility probe, not an anti-cheat proof.
    It hooks module-level Python/NumPy calls, ``random.Random`` instances,
    NumPy ``Generator``/``RandomState`` constructors and ``default_rng``
    instances. Native Blender/C++ randomness and third-party RNGs remain
    outside the scope.
    """
    counters: dict[str, int] = {}
    originals: dict[str, object] = {}
    instance_records: list[dict[str, object]] = []
    for name in _RNG_FUNCTIONS:
        original = getattr(random, name, None)
        if not callable(original):
            continue
        originals[name] = original

        def wrapped(*args, _name=name, _original=original, **kwargs):
            counters[_name] = counters.get(_name, 0) + 1
            return _original(*args, **kwargs)

        setattr(random, name, wrapped)

    original_random_class = random.Random

    def instance_call(record: dict[str, object], name: str, function, *args, **kwargs):
        key = f"python.Random.{name}"
        counters[key] = counters.get(key, 0) + 1
        result = function(*args, **kwargs)
        record["state_after"] = _state_digest(record["instance"].getstate())
        return result

    class TracedRandom(original_random_class):
        def __init__(self, *args, **kwargs):
            self._l1_trace_record = None
            super().__init__(*args, **kwargs)
            record: dict[str, object] = {
                "index": len(instance_records),
                "instance": self,
                "state_before": _state_digest(self.getstate()),
                "state_after": _state_digest(self.getstate()),
                "calls": {},
            }
            instance_records.append(record)
            self._l1_trace_record = record

        def _l1_call(self, name, *args, **kwargs):
            record = self._l1_trace_record
            if record is None:
                return getattr(original_random_class, name)(self, *args, **kwargs)
            calls = record["calls"]
            calls[name] = calls.get(name, 0) + 1
            return instance_call(record, name, getattr(original_random_class, name), self, *args, **kwargs)

    for name in (
        "random",
        "randint",
        "randrange",
        "choice",
        "choices",
        "sample",
        "shuffle",
        "uniform",
        "getrandbits",
        "seed",
    ):
        if hasattr(original_random_class, name):
            setattr(
                TracedRandom,
                name,
                lambda self, *args, _name=name, **kwargs: self._l1_call(
                    _name, *args, **kwargs
                ),
            )
    random.Random = TracedRandom

    numpy_module = None
    numpy_originals: dict[str, object] = {}
    numpy_instance_records: dict[str, list[dict[str, object]]] = {
        "Generator": [],
        "RandomState": [],
    }
    try:
        import numpy as numpy_module  # type: ignore[import-not-found]

        numpy_functions = ("random", "randint", "rand", "uniform", "choice", "shuffle")
        for name in numpy_functions:
            original = getattr(numpy_module.random, name, None)
            if not callable(original):
                continue
            numpy_originals[name] = original

            def numpy_wrapped(*args, _name=name, _original=original, **kwargs):
                key = f"numpy.random.{_name}"
                counters[key] = counters.get(key, 0) + 1
                return _original(*args, **kwargs)

            setattr(numpy_module.random, name, numpy_wrapped)

        def numpy_instance_digest(instance) -> str | None:
            try:
                return _state_digest(instance.bit_generator.state)
            except (AttributeError, TypeError, ValueError):
                try:
                    return _state_digest(instance.get_state())
                except (AttributeError, TypeError, ValueError):
                    return None

        def _record_numpy_instance(instance, family: str, construction: str):
            records = numpy_instance_records[family]
            record: dict[str, object] = {
                "index": len(records),
                "construction": construction,
                "instance": instance,
                "inner": instance,
                "state_before": numpy_instance_digest(instance),
                "state_after": numpy_instance_digest(instance),
                "calls": {},
            }
            records.append(record)
            return record

        def _numpy_instance_call(
            family: str,
            record: dict[str, object] | None,
            instance,
            name: str,
            *args,
            **kwargs,
        ):
            if record is None:
                return getattr(instance, name)(*args, **kwargs)
            calls = record["calls"]
            calls[name] = calls.get(name, 0) + 1
            key = f"numpy.{family}.{name}"
            counters[key] = counters.get(key, 0) + 1
            inner = record.get("inner", instance)
            result = getattr(inner, name)(*args, **kwargs)
            record["state_after"] = numpy_instance_digest(inner)
            return result

        original_generator_class = numpy_module.random.Generator
        original_randomstate_class = numpy_module.random.RandomState

        generator_methods = (
            "random",
            "integers",
            "uniform",
            "choice",
            "shuffle",
            "normal",
            "standard_normal",
            "exponential",
            "poisson",
            "permutation",
        )
        randomstate_methods = (
            "random",
            "random_sample",
            "rand",
            "randn",
            "randint",
            "choice",
            "shuffle",
            "uniform",
            "normal",
            "standard_normal",
            "permutation",
            "seed",
        )

        class TracedGenerator:
            def __new__(cls, *args, **kwargs):
                instance = object.__new__(cls)
                inner = original_generator_class(*args, **kwargs)
                counters["numpy.Generator.constructor"] = counters.get(
                    "numpy.Generator.constructor", 0
                ) + 1
                instance._l1_inner = inner
                instance._l1_trace_record = _record_numpy_instance(
                    instance, "Generator", "constructor"
                )
                instance._l1_trace_record["inner"] = inner
                instance._l1_trace_record["state_before"] = numpy_instance_digest(inner)
                instance._l1_trace_record["state_after"] = numpy_instance_digest(inner)
                return instance

            def _l1_call(self, name, *args, **kwargs):
                return _numpy_instance_call(
                    "Generator",
                    getattr(self, "_l1_trace_record", None),
                    self,
                    name,
                    *args,
                    **kwargs,
                )

            @classmethod
            def _from_inner(cls, inner, construction: str):
                instance = object.__new__(cls)
                instance._l1_inner = inner
                instance._l1_trace_record = _record_numpy_instance(
                    instance, "Generator", construction
                )
                instance._l1_trace_record["inner"] = inner
                instance._l1_trace_record["state_before"] = numpy_instance_digest(inner)
                instance._l1_trace_record["state_after"] = numpy_instance_digest(inner)
                return instance

            def __getattr__(self, name):
                return getattr(self._l1_inner, name)

        class TracedRandomState:
            def __new__(cls, *args, **kwargs):
                instance = object.__new__(cls)
                inner = original_randomstate_class(*args, **kwargs)
                counters["numpy.RandomState.constructor"] = counters.get(
                    "numpy.RandomState.constructor", 0
                ) + 1
                instance._l1_inner = inner
                instance._l1_trace_record = _record_numpy_instance(
                    instance, "RandomState", "constructor"
                )
                instance._l1_trace_record["inner"] = inner
                instance._l1_trace_record["state_before"] = numpy_instance_digest(inner)
                instance._l1_trace_record["state_after"] = numpy_instance_digest(inner)
                return instance

            def _l1_call(self, name, *args, **kwargs):
                return _numpy_instance_call(
                    "RandomState",
                    getattr(self, "_l1_trace_record", None),
                    self,
                    name,
                    *args,
                    **kwargs,
                )

            def __getattr__(self, name):
                return getattr(self._l1_inner, name)

        for name in generator_methods:
            if hasattr(original_generator_class, name):
                setattr(
                    TracedGenerator,
                    name,
                    lambda self, *args, _name=name, **kwargs: self._l1_call(
                        _name, *args, **kwargs
                    ),
                )
        for name in randomstate_methods:
            if hasattr(original_randomstate_class, name):
                setattr(
                    TracedRandomState,
                    name,
                    lambda self, *args, _name=name, **kwargs: self._l1_call(
                        _name, *args, **kwargs
                    ),
                )

        numpy_originals["Generator"] = original_generator_class
        numpy_originals["RandomState"] = original_randomstate_class
        numpy_module.random.Generator = TracedGenerator
        numpy_module.random.RandomState = TracedRandomState

        default_rng = getattr(numpy_module.random, "default_rng", None)
        if callable(default_rng):
            numpy_originals["default_rng"] = default_rng

            def default_rng_wrapped(*args, _original=default_rng, **kwargs):
                counters["numpy.random.default_rng"] = counters.get(
                    "numpy.random.default_rng", 0
                ) + 1
                inner = _original(*args, **kwargs)
                if isinstance(inner, TracedGenerator):
                    record = getattr(inner, "_l1_trace_record", None)
                    if record is not None:
                        record["construction"] = "default_rng"
                    return inner
                return TracedGenerator._from_inner(inner, "default_rng")

            numpy_module.random.default_rng = default_rng_wrapped
    except (ImportError, AttributeError, TypeError):
        numpy_module = None

    before_random = _state_digest(random.getstate())
    before_numpy = None
    if numpy_module is not None:
        try:
            before_numpy = _state_digest(numpy_module.random.get_state())
        except (AttributeError, ValueError):
            before_numpy = None
    seed = os.environ.get("THREEDBENCH_SEED", os.environ.get("BENCHMARK_SEED"))

    def finish() -> dict[str, object]:
        after_random = _state_digest(random.getstate())
        after_numpy = None
        if numpy_module is not None:
            try:
                after_numpy = _state_digest(numpy_module.random.get_state())
            except (AttributeError, ValueError):
                after_numpy = None
        for name, original in originals.items():
            setattr(random, name, original)
        random.Random = original_random_class
        if numpy_module is not None:
            for name, original in numpy_originals.items():
                setattr(numpy_module.random, name, original)
        for record in instance_records:
            record.pop("instance", None)
        numpy_instances = {}
        for family, records in numpy_instance_records.items():
            for record in records:
                record.pop("instance", None)
                record.pop("inner", None)
            numpy_instances[family] = records
        # Keep the original v1 key while exposing the constructor family names
        # used by the expanded trace.  Existing readers therefore remain
        # compatible with the new direct-constructor evidence.
        numpy_instances["numpy_generator"] = numpy_instances["Generator"]
        numpy_instances["numpy_randomstate"] = numpy_instances["RandomState"]
        return {
            "protocol": "l1-rng-trace-v1",
            "status": "observed",
            "program_seed": int(seed) if seed is not None and seed.isdigit() else seed,
            "module_calls": dict(sorted(counters.items())),
            "total_module_calls": sum(counters.values()),
            "instances": {"python_random": instance_records, **numpy_instances},
            "state_before": {"python_random": before_random, "numpy_random": before_numpy},
            "state_after": {"python_random": after_random, "numpy_random": after_numpy},
            "state_changed": {
                "python_random": before_random != after_random,
                "numpy_random": before_numpy != after_numpy
                if before_numpy is not None and after_numpy is not None
                else None,
            },
            "scope": [
                "module-level Python random functions",
                "module-level NumPy random functions when NumPy is available",
                "explicit random.Random instances",
                "NumPy Generator and RandomState constructors",
                "NumPy default_rng Generator instances",
            ],
            "limitations": [
                "Third-party RNGs and direct C-extension calls that bypass these NumPy classes are not hooked.",
                "Blender/C++ internal randomness is not hooked.",
                "This trace is reproducibility evidence, not an anti-cheating proof.",
            ],
        }

    return finish


def _emit_rng_trace(trace: dict[str, object]) -> None:
    stream = getattr(sys, "__stdout__", None) or sys.stdout
    stream.write(f"[l1-rng-trace] {json.dumps(trace, sort_keys=True)}\n")
    stream.flush()


def _arguments() -> argparse.Namespace:
    try:
        separator = sys.argv.index("--")
    except ValueError as error:
        raise RuntimeError(
            "Renderer arguments must follow Blender's '--' separator"
        ) from error

    parser = argparse.ArgumentParser(
        description="Execute one generated script inside Blender."
    )
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--working-dir", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(sys.argv[separator + 1 :])


def _execute_script(script: Path) -> None:
    source = script.read_text(encoding="utf-8")
    script_directory = str(script.parent)
    if script_directory not in sys.path:
        sys.path.insert(0, script_directory)

    namespace = {
        "__name__": "__main__",
        "__file__": str(script),
        "__package__": None,
        "__cached__": None,
    }
    exec(compile(source, str(script), "exec"), namespace, namespace)  # noqa: S102


def main() -> None:
    args = _arguments()
    script = args.script.expanduser().resolve()
    output = args.output.expanduser().resolve()
    working_directory = (args.working_dir or script.parent).expanduser().resolve()

    if not script.is_file():
        raise FileNotFoundError(f"Generated script does not exist: {script}")
    if not working_directory.is_dir():
        raise FileNotFoundError(
            f"Script working directory does not exist: {working_directory}"
        )
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Output already exists: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    os.chdir(working_directory)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    print(f"[render] executing {script}", flush=True)
    finish_rng_trace = _install_rng_trace()
    try:
        _execute_script(script)
    finally:
        _emit_rng_trace(finish_rng_trace())

    # Benchmark outputs are regenerated explicitly with --overwrite; Blender's
    # numbered .blend1/.blend2 backups would otherwise accumulate per sample.
    bpy.context.preferences.filepaths.save_version = 0
    result = bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=False)
    if "FINISHED" not in result:
        raise RuntimeError(f"Blender could not save the scene to {output}: {result}")
    print(f"[render] saved {output}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except BaseException:  # noqa: BLE001 - report every Blender worker failure
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        # This process is a dedicated one-shot Blender worker. Bypass Blender's
        # shutdown hooks because some headless Linux hosts hang in audio cleanup.
        os._exit(1)
    else:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
