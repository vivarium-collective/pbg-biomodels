#!/usr/bin/env python3
"""Build the committed corpus comparison dataset (Task Z0).

Reads the per-model tidy time-course parquets produced by the full
compare-all sweep (``out/compare_all_1054/series/*.parquet``, columns
``[job, engine, variable, time, value]``), keeps only the ``copasi`` and
``tellurium`` engines, downsamples each ``(biomodel_id, job, engine,
variable)`` series to at most ``--max-points`` rows by even stride, and
concatenates everything into one small, git-friendly parquet:
``datasets/corpus_comparison/corpus_timecourse.parquet``.

It also derives a small pairwise-metrics summary
(``datasets/corpus_comparison/corpus_metrics.json``) from
``out/compare_all_1054/index.json``, keeping only the copasi<->tellurium
comparison per (biomodel_id, job).

Usage:
    .venv/bin/python scripts/build_corpus_dataset.py \\
        --source out/compare_all_1054 --out datasets/corpus_comparison

The core logic (``build_dataset`` / ``downsample_group`` / ``derive_bucket``)
is exercised directly by ``tests/test_corpus_dataset.py`` against a tiny
synthetic source directory, independent of the CLI.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ENGINES = ("copasi", "tellurium")
DEFAULT_MAX_POINTS = 100
FALLBACK_MAX_POINTS = 60
FALLBACK_SIZE_LIMIT_BYTES = 15 * 1024 * 1024  # ~15 MB target

TIMECOURSE_COLUMNS = ["biomodel_id", "job", "engine", "variable", "time", "value"]


def downsample_group(df: pd.DataFrame, max_points: int) -> pd.DataFrame:
    """Downsample one series (already isolated to one biomodel/job/engine/
    variable) to at most ``max_points`` rows by even stride, keeping the
    first and last timepoints.
    """
    n = len(df)
    if n <= max_points:
        return df
    idx = np.unique(np.round(np.linspace(0, n - 1, max_points)).astype(int))
    return df.iloc[idx]


def derive_bucket(nrmse: float | None) -> str:
    """Bucket an NRMSE value using the same cut points as the corpus-wide
    ``bucket`` field in ``index.json`` (good < 0.01 <= borderline < 0.1 <=
    large), applied here to the single copasi<->tellurium pair rather than
    the corpus's multi-engine max.
    """
    if nrmse is None or (isinstance(nrmse, float) and np.isnan(nrmse)):
        return "none"
    if nrmse < 0.01:
        return "good"
    if nrmse < 0.1:
        return "borderline"
    return "large"


def _load_and_filter_series(parquet_path: Path, biomodel_id: str, max_points: int) -> pd.DataFrame | None:
    df = pd.read_parquet(parquet_path)
    df = df[df["engine"].astype(str).isin(ENGINES)]
    if df.empty:
        return None

    parts = []
    for (job, engine, variable), group in df.groupby(["job", "engine", "variable"], observed=True):
        group = group.sort_values("time")
        parts.append(downsample_group(group, max_points))
    out = pd.concat(parts, ignore_index=True)
    out["biomodel_id"] = biomodel_id
    out["time"] = out["time"].astype(np.float32)
    out["value"] = out["value"].astype(np.float32)
    return out[TIMECOURSE_COLUMNS]


def build_timecourse(source_dir: Path, max_points: int = DEFAULT_MAX_POINTS) -> tuple[pd.DataFrame, dict]:
    series_dir = source_dir / "series"
    parquet_paths = sorted(series_dir.glob("*.parquet"))

    frames = []
    n_with_data = 0
    n_skipped = 0
    for path in parquet_paths:
        biomodel_id = path.stem
        frame = _load_and_filter_series(path, biomodel_id, max_points)
        if frame is None:
            n_skipped += 1
            continue
        n_with_data += 1
        frames.append(frame)

    if frames:
        timecourse = pd.concat(frames, ignore_index=True)
    else:
        timecourse = pd.DataFrame(columns=TIMECOURSE_COLUMNS)

    for col in ("biomodel_id", "job", "engine", "variable"):
        timecourse[col] = timecourse[col].astype("category")

    stats = {
        "n_models_scanned": len(parquet_paths),
        "n_models_with_data": n_with_data,
        "n_models_skipped": n_skipped,
        "n_rows": len(timecourse),
    }
    return timecourse, stats


def compute_metrics(source_dir: Path, timecourse: pd.DataFrame) -> dict:
    index_path = source_dir / "index.json"
    if not index_path.exists():
        return {}
    index = json.loads(index_path.read_text(encoding="utf-8"))
    models = index.get("models", {})

    # n_shared per (biomodel_id, job): number of variables present in BOTH
    # copasi and tellurium series (computed from the already-filtered
    # timecourse, so it reflects what's actually in the committed dataset).
    shared_counts: dict[tuple[str, str], int] = {}
    if not timecourse.empty:
        variable_sets: dict[tuple[str, str, str], set[str]] = {}
        by_key = timecourse.groupby(["biomodel_id", "job", "engine"], observed=True)["variable"]
        for (biomodel_id, job, engine), variables in by_key:
            variable_sets[(str(biomodel_id), str(job), str(engine))] = set(variables.astype(str))

        model_jobs = {(bid, job) for (bid, job, _engine) in variable_sets}
        for biomodel_id, job in model_jobs:
            copasi_vars = variable_sets.get((biomodel_id, job, "copasi"))
            tellurium_vars = variable_sets.get((biomodel_id, job, "tellurium"))
            if copasi_vars is not None and tellurium_vars is not None:
                shared_counts[(biomodel_id, job)] = len(copasi_vars & tellurium_vars)

    metrics: dict = {}
    for biomodel_id, model_entry in models.items():
        jobs = model_entry.get("jobs", {})
        for job, job_entry in jobs.items():
            matrix = job_entry.get("matrix", {})
            copasi_row = matrix.get("copasi")
            if not copasi_row or "tellurium" not in copasi_row:
                continue
            nrmse = copasi_row["tellurium"]
            n_shared = shared_counts.get((biomodel_id, job))
            if n_shared is None:
                # Pair not present in the (filtered) timecourse for this
                # model/job -- skip rather than fabricate a count.
                continue
            metrics.setdefault(biomodel_id, {}).setdefault(job, {})["copasi__tellurium"] = {
                "mean_nrmse": nrmse,
                "bucket": derive_bucket(nrmse),
                "n_shared": n_shared,
            }
    return metrics


def build_dataset(source_dir: Path, out_dir: Path, max_points: int = DEFAULT_MAX_POINTS) -> dict:
    source_dir = Path(source_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    timecourse, stats = build_timecourse(source_dir, max_points=max_points)
    parquet_path = out_dir / "corpus_timecourse.parquet"
    timecourse.to_parquet(parquet_path, index=False)

    metrics = compute_metrics(source_dir, timecourse)
    metrics_path = out_dir / "corpus_metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")

    stats["parquet_bytes"] = parquet_path.stat().st_size
    stats["n_models_with_metrics"] = len(metrics)
    stats["max_points"] = max_points
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--source",
        default="/Users/eranagmon/code/pbg-biomodels/out/compare_all_1054",
        help="Directory containing series/*.parquet + index.json",
    )
    ap.add_argument("--out", default="datasets/corpus_comparison", help="Output directory")
    ap.add_argument("--max-points", type=int, default=DEFAULT_MAX_POINTS)
    args = ap.parse_args()

    source_dir = Path(args.source)
    out_dir = Path(args.out)

    max_points = args.max_points
    stats = build_dataset(source_dir, out_dir, max_points=max_points)

    if stats["parquet_bytes"] > FALLBACK_SIZE_LIMIT_BYTES and max_points > FALLBACK_MAX_POINTS:
        print(
            f"corpus_timecourse.parquet is {stats['parquet_bytes'] / 1e6:.1f} MB "
            f"(> ~15 MB target) at max_points={max_points}; rebuilding at "
            f"max_points={FALLBACK_MAX_POINTS}."
        )
        max_points = FALLBACK_MAX_POINTS
        stats = build_dataset(source_dir, out_dir, max_points=max_points)

    print(f"models scanned:       {stats['n_models_scanned']}")
    print(f"models with data:     {stats['n_models_with_data']}")
    print(f"models skipped:       {stats['n_models_skipped']}")
    print(f"models with metrics:  {stats['n_models_with_metrics']}")
    print(f"rows:                 {stats['n_rows']}")
    print(f"max_points/series:    {stats['max_points']}")
    print(f"parquet size:         {stats['parquet_bytes'] / 1e6:.2f} MB")
    if stats["parquet_bytes"] > FALLBACK_SIZE_LIMIT_BYTES:
        print(f"NOTE: parquet still exceeds ~15 MB target even at max_points={max_points}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
