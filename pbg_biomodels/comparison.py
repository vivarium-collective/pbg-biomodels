"""Shared simulator-comparison math.

Used by both the post-hoc HTML report builder (``analysis.py``) and the
runtime :class:`SimulatorComparisonStep` (``steps/simulator_comparison.py``).

Inputs are per-engine ``numeric_result`` payloads — dicts of shape
``{time: list[float], columns: list[str], values: list[list[float]]}``,
emitted by the COPASI / Tellurium UTC steps.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional


# Normalized-RMSE thresholds (mean across shared species).
BUCKET_THRESHOLDS = [
    ("good",       0.01,     "Good (≤1%)"),
    ("borderline", 0.10,     "Borderline (1–10%)"),
    ("large",      math.inf, "Large diff (>10%)"),
]
NO_COMPARISON_BUCKET = ("none", "No comparison")


def union_species(engines: Dict[str, Any]) -> List[str]:
    """Return the ordered union of species columns across all engines."""
    species: List[str] = []
    seen: set = set()
    for payload in engines.values():
        if not payload:
            continue
        for c in payload.get("columns", []):
            if c not in seen:
                seen.add(c)
                species.append(c)
    return species


def compare_two_engines(
    engine_a: Optional[Dict[str, Any]],
    engine_b: Optional[Dict[str, Any]],
    name_a: str = "a",
    name_b: str = "b",
) -> Dict[str, Any]:
    """Compare two numeric_result payloads species-by-species.

    Computes RMSE and normalized RMSE (RMSE / max|y|) for every species that
    appears in BOTH engines' columns, then a mean nRMSE across shared species
    and a coarse bucket label.

    Returns the shape consumed by the HTML report's metadata card and the
    dashboard Step. Returns the ``none`` bucket if either engine is missing
    or no species are shared.
    """
    engines = {name_a: engine_a, name_b: engine_b}
    species = union_species(engines)

    rmse_by_species: Dict[str, float] = {}
    nrmse_by_species: Dict[str, float] = {}
    n_shared = 0

    for sp in species:
        ys_per_engine: Dict[str, List[float]] = {}
        for eng_name, payload in engines.items():
            if not payload:
                continue
            cols = payload.get("columns", [])
            if sp not in cols:
                continue
            j = cols.index(sp)
            ys_per_engine[eng_name] = [row[j] for row in payload.get("values", [])]
        if len(ys_per_engine) < 2:
            continue
        n_shared += 1
        keys = sorted(ys_per_engine.keys())
        y1, y2 = ys_per_engine[keys[0]], ys_per_engine[keys[1]]
        n = min(len(y1), len(y2))
        if n == 0:
            continue
        rmse = math.sqrt(sum((y1[k] - y2[k]) ** 2 for k in range(n)) / n)
        rmse_by_species[sp] = rmse
        denom = max((abs(v) for v in y1[:n]), default=0.0)
        denom = max(denom, max((abs(v) for v in y2[:n]), default=0.0))
        if denom > 0:
            nrmse_by_species[sp] = rmse / denom

    if nrmse_by_species:
        mean_nrmse: Optional[float] = sum(nrmse_by_species.values()) / len(nrmse_by_species)
    else:
        mean_nrmse = None

    if mean_nrmse is None:
        bucket_id, bucket_label = NO_COMPARISON_BUCKET
    else:
        for bid, threshold, label in BUCKET_THRESHOLDS:
            if mean_nrmse <= threshold:
                bucket_id, bucket_label = bid, label
                break

    return {
        "n_shared": n_shared,
        "rmse_by_species": rmse_by_species,
        "nrmse_by_species": nrmse_by_species,
        "mean_nrmse": mean_nrmse,
        "bucket": bucket_id,
        "bucket_label": bucket_label,
    }


def bucket_for(mean_nrmse: Optional[float]) -> tuple:
    """Map a mean-nRMSE value to a ``(bucket_id, bucket_label)`` pair."""
    if mean_nrmse is None:
        return NO_COMPARISON_BUCKET
    for bid, threshold, label in BUCKET_THRESHOLDS:
        if mean_nrmse <= threshold:
            return bid, label
    return BUCKET_THRESHOLDS[-1][0], BUCKET_THRESHOLDS[-1][2]


def compare_n_engines(engines: Dict[str, Optional[Dict[str, Any]]]) -> Dict[str, Any]:
    """All-pairs comparison across N named engines (simulators + references).

    Runs :func:`compare_two_engines` on every unordered pair of engines that
    carry data, and summarizes the worst (largest mean-nRMSE) pair.

    Returns::

        {
          "engines":   ["copasi", "tellurium", ...],   # engines with data
          "pairs": {
            "copasi__tellurium": {<compare_two_engines result>}, ...
          },
          "matrix":    {a: {b: mean_nrmse_or_None}},     # symmetric, diag None
          "max_nrmse": float | None,                     # worst pair's mean nRMSE
          "worst_pair": [a, b] | None,
          "bucket":     str,                             # bucket of the worst pair
          "bucket_label": str,
        }
    """
    present = sorted(
        name for name, payload in engines.items()
        if payload and payload.get("columns")
    )

    pairs: Dict[str, Any] = {}
    matrix: Dict[str, Dict[str, Optional[float]]] = {
        a: {b: None for b in present} for a in present
    }
    max_nrmse: Optional[float] = None
    worst_pair: Optional[List[str]] = None

    for i, a in enumerate(present):
        for b in present[i + 1:]:
            result = compare_two_engines(engines[a], engines[b], name_a=a, name_b=b)
            pairs[f"{a}__{b}"] = result
            mean = result.get("mean_nrmse")
            matrix[a][b] = mean
            matrix[b][a] = mean
            if mean is not None and (max_nrmse is None or mean > max_nrmse):
                max_nrmse = mean
                worst_pair = [a, b]

    bucket_id, bucket_label = bucket_for(max_nrmse)
    return {
        "engines": present,
        "pairs": pairs,
        "matrix": matrix,
        "max_nrmse": max_nrmse,
        "worst_pair": worst_pair,
        "bucket": bucket_id,
        "bucket_label": bucket_label,
    }


def compare_two_engines_steady_state(
    engine_a: Optional[Dict[str, float]],
    engine_b: Optional[Dict[str, float]],
    name_a: str = "a",
    name_b: str = "b",
    eps: float = 1e-30,
) -> Dict[str, Any]:
    """Compare two `{observable_name: float}` maps observable-by-observable.

    Metric: `|a-b| / max(|a|, |b|, eps)` per shared observable; the result's
    `mean_nrmse` is the mean across shared observables. Buckets use the same
    `BUCKET_THRESHOLDS` as the UTC version so the vocabulary is shared.
    """
    a = engine_a or {}
    b = engine_b or {}
    shared = sorted(set(a) & set(b))
    nrmse_by_species: Dict[str, float] = {}
    for sp in shared:
        denom = max(abs(a[sp]), abs(b[sp]), eps)
        nrmse_by_species[sp] = abs(a[sp] - b[sp]) / denom

    if nrmse_by_species:
        mean_nrmse: Optional[float] = (
            sum(nrmse_by_species.values()) / len(nrmse_by_species)
        )
    else:
        mean_nrmse = None

    bucket_id, bucket_label = bucket_for(mean_nrmse)
    return {
        "n_shared":         len(shared),
        "rmse_by_species":  {},  # SS pairs have no time-series RMSE
        "nrmse_by_species": nrmse_by_species,
        "mean_nrmse":       mean_nrmse,
        "bucket":           bucket_id,
        "bucket_label":     bucket_label,
    }


def compare_n_engines_steady_state(
    engines: Dict[str, Optional[Dict[str, float]]],
) -> Dict[str, Any]:
    """All-pairs steady-state comparison across N named engines.

    Same return shape as :func:`compare_n_engines`, but each pair is
    scored with the steady-state metric. Engines with no observables
    (or `None`) are dropped from the comparison.
    """
    present = sorted(name for name, obs in engines.items() if obs)
    pairs: Dict[str, Any] = {}
    matrix: Dict[str, Dict[str, Optional[float]]] = {
        a: {b: None for b in present} for a in present
    }
    max_nrmse: Optional[float] = None
    worst_pair: Optional[List[str]] = None

    for i, a in enumerate(present):
        for b in present[i + 1:]:
            result = compare_two_engines_steady_state(
                engines[a], engines[b], name_a=a, name_b=b,
            )
            pairs[f"{a}__{b}"] = result
            mean = result.get("mean_nrmse")
            matrix[a][b] = mean
            matrix[b][a] = mean
            if mean is not None and (max_nrmse is None or mean > max_nrmse):
                max_nrmse = mean
                worst_pair = [a, b]

    bucket_id, bucket_label = bucket_for(max_nrmse)
    return {
        "engines":      present,
        "pairs":        pairs,
        "matrix":       matrix,
        "max_nrmse":    max_nrmse,
        "worst_pair":   worst_pair,
        "bucket":       bucket_id,
        "bucket_label": bucket_label,
    }
