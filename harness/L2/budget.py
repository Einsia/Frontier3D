"""L2 timeout ladders: advance on timeouts, never on a quality failure."""
import math


def timeout_steps(section):
    base = section["timeout_seconds"]
    values = section.get("timeout_steps_seconds", [base])
    if not isinstance(values, list) or not values:
        raise ValueError("timeout_steps_seconds must be a nonempty list")
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError("Timeout steps must be positive finite numbers")
    if values[0] != base or any(a >= b for a, b in zip(values, values[1:])):
        raise ValueError("Timeout steps must start at timeout_seconds and strictly increase")
    return tuple(float(v) for v in values)


def has_timeout(record):
    for result in record.get("seed_runs", {}).values():
        if result.get("execution", {}).get("status") in {"timeout", "budget_exhausted"}:
            return True
        if any(step.get("status") in {"timeout", "budget_exhausted"}
               for step in result.get("inspection_processes", {}).values()):
            return True
    return record.get("baseline_execution", {}).get("status") in {"timeout", "budget_exhausted"}
