"""Shared helpers for the ``results`` leaf — a flat ``map[observable -> timeseries]``.

The batch-compare composite stores one leaf per
``(biomodel_id, sedml_job_id, simulator)``. Each leaf is a plain mapping from
observable name to its timeseries (``list[float]``):

* **UTC** jobs carry the sample times under the reserved key ``"time"``; every
  other key is an observable's trajectory (same length as ``time``).
* **steady-state** jobs omit ``"time"`` and store each observable as a length-1
  list — the single steady-state value.

Classification is therefore purely structural: a leaf is UTC iff it has a
``"time"`` key. Keeping these accessors in one module stops the runner (which
writes leaves), the comparison Step, and the overlay viz (which both read them)
from drifting apart on the leaf format.
"""
from __future__ import annotations

from typing import Any, Dict, List

# Reserved observable name for the sample-time vector inside a UTC leaf.
TIME_KEY = "time"


def is_utc(leaf: Dict[str, Any]) -> bool:
    """True for a UTC leaf (has a time vector); False for steady-state."""
    return TIME_KEY in (leaf or {})


def kind_of(leaf: Dict[str, Any]) -> str:
    """``"utc"`` or ``"steady_state"`` inferred structurally from the leaf."""
    return "utc" if is_utc(leaf) else "steady_state"


def time_of(leaf: Dict[str, Any]) -> List[float]:
    """The reserved time vector (empty list when absent)."""
    return list((leaf or {}).get(TIME_KEY) or [])


def observables_of(leaf: Dict[str, Any]) -> Dict[str, Any]:
    """Every series except the reserved ``time`` vector."""
    return {k: v for k, v in (leaf or {}).items() if k != TIME_KEY}


def to_numeric_result(leaf: Dict[str, Any]) -> Dict[str, Any]:
    """UTC leaf -> ``{time, columns, values}`` (the shape the comparison math wants)."""
    obs = observables_of(leaf)
    cols = list(obs.keys())
    n_rows = min((len(obs[c]) for c in cols), default=0)
    values = [[float(obs[c][r]) for c in cols] for r in range(n_rows)]
    return {"time": time_of(leaf), "columns": cols, "values": values}


def steady_state_scalars(leaf: Dict[str, Any]) -> Dict[str, float]:
    """Steady-state leaf -> ``{observable: scalar}`` (unwraps length-1 lists)."""
    out: Dict[str, float] = {}
    for k, v in observables_of(leaf).items():
        if isinstance(v, (list, tuple)):
            out[k] = float(v[0]) if v else 0.0
        else:
            out[k] = float(v)
    return out
