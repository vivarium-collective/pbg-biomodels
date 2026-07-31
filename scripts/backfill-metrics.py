#!/usr/bin/env python3
"""Backfill both comparison metrics into an existing two-tier index.json.

The salvaged ``compare_all_1054`` index predates the closeness metric, so its
closeness columns are empty. The per-model time series are on disk in
``series/<bid>.parquet``, so we can recompute BOTH metrics (nRMSE + closeness)
from them **without re-running any simulation** and rewrite the index job
entries in place. Run provenance (per-engine status/error) is NOT recovered —
that needs a fresh run.

Usage:
    .venv/bin/python scripts/backfill-metrics.py --out-dir out/compare_all_1054
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default="out/compare_all_1054")
    args = ap.parse_args()

    od = Path(args.out_dir)
    index_path = od / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    models = index.get("models") or {}

    # Lazy heavy imports so --help is instant.
    from viva_biomodels import register_types
    from viva_biomodels.core import build_core
    from viva_biomodels.lazy_viewer import _parquet_leaves_aligned
    from viva_biomodels.steps.simulator_comparison import BatchCompareStep

    core = register_types(build_core())
    step = BatchCompareStep(core=core)

    n, changed = 0, 0
    for bid, m in models.items():
        n += 1
        leaves_by_job = _parquet_leaves_aligned(od, bid)  # {job: {engine: leaf}}
        if not leaves_by_job:
            continue
        comps = step.update({"results": {bid: leaves_by_job}})["comparisons"]
        model_comps = comps.get(bid) or {}
        for job, je in (m.get("jobs") or {}).items():
            c = model_comps.get(job) or {}
            leaves = leaves_by_job.get(job) or {}
            je["engines"] = c.get("engines") or sorted(leaves.keys())
            je["matrix"] = c.get("matrix") or {}
            je["max_nrmse"] = c.get("max_nrmse")
            je["bucket"] = c.get("bucket")
            je["matrix_closeness"] = c.get("matrix_closeness") or {}
            je["max_score"] = c.get("max_score")
            je["closeness_bucket"] = c.get("closeness_bucket")
            je["n_ok"] = sum(1 for v in leaves.values() if v)
            changed += 1
        if n % 100 == 0:
            print(f"  … {n}/{len(models)} models")

    backup = index_path.with_suffix(".json.bak")
    if not backup.exists():
        shutil.copy2(index_path, backup)
    index.setdefault("meta", {})["metrics_backfilled_from_parquet"] = True
    index_path.write_text(json.dumps(index), encoding="utf-8")
    print(f"Backfilled {changed} job entries across {n} models -> {index_path}")
    print(f"Backup: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
