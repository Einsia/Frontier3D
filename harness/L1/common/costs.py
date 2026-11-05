"""Keep unknown-cost pointers consistent without inventing measurements."""

from __future__ import annotations

from typing import Any


def refresh_unknown_costs(costs: dict[str, Any]) -> None:
    """Index recorded nulls; this does not prove completeness or cost provenance.

    Source pointers retain the existing short form (without ``sources.``).
    Measured zero is known; missing/unmeasured values remain null. Status fields
    describe execution, and are not changed when their measurements are unknown.
    """
    unknown = [key for key, value in costs.items() if value is None]
    for source, values in costs.get("sources", {}).items():
        unknown.extend(f"{source}.{key}" for key, value in values.items() if value is None)
    costs["unknown"] = sorted(unknown)
