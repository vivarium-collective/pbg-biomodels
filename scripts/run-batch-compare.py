#!/usr/bin/env python3
"""Run the batch-compare-biomodels composite and persist the results store.

Drives the `batch-compare-biomodels` composite over a set of BioModels under a
set of simulators, then writes the nested results/comparisons/diagnostics store
to ``.pbg/last_batch_results.json`` — the payload ``render-batch-compare.py``
turns into the viewer HTML.

Usage:
    python scripts/run-batch-compare.py [-n 10] [--simulators copasi,tellurium,simbio,amici]

With no --simulators, uses every installed engine (ALL_SIMULATORS). amici
compiles a C++ extension per model on first use, so a 4-engine / 10-model run
can take several minutes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from process_bigraph import Composite, gather_emitter_results

from pbg_biomodels import register_types
from pbg_biomodels.core import build_core
from pbg_biomodels.simulators import ALL_SIMULATORS, resolve_simulators
from pbg_superpowers.composite_generator import _REGISTRY, build_generator
import pbg_biomodels.composites.batch_compare_biomodels  # noqa: F401  (registers generator)


def run(ids, simulators) -> dict:
    core = register_types(build_core())
    entry = next(e for e in _REGISTRY.values() if e.name == "batch-compare-biomodels")
    doc = build_generator(entry, overrides={
        "biomodel_ids": list(ids),
        "simulators":   list(simulators),
    })
    composite = Composite(doc, core=core)
    composite.run(0.0)
    snap = (gather_emitter_results(composite).get(("emitter",)) or [{}])[-1]
    return {
        "results":     snap.get("results") or {},
        "comparisons": snap.get("comparisons") or {},
        "diagnostics": snap.get("diagnostics") or {},
        "ids":         list(ids),
    }


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", "--number-of-models", type=int, default=10)
    ap.add_argument("--simulators", default=None,
                    help="comma-separated; default = all installed engines")
    ap.add_argument("--out", type=Path,
                    default=root / ".pbg" / "last_batch_results.json")
    args = ap.parse_args()

    ids = [f"BIOMD{n:010d}" for n in range(1, args.number_of_models + 1)]
    sims = resolve_simulators(args.simulators) if args.simulators else list(ALL_SIMULATORS)
    print(f"Running {len(ids)} model(s) under {sims} ...")

    store = run(ids, sims)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(store), encoding="utf-8")

    # Quick coverage summary per simulator.
    diag_runs = store["diagnostics"].get("runs") or {}
    ok = {s: 0 for s in sims}
    fail = {s: 0 for s in sims}
    for bid, jobs in diag_runs.items():
        for job, simmap in jobs.items():
            for s, rec in simmap.items():
                (ok if rec.get("status") == "ok" else fail)[s] = \
                    (ok if rec.get("status") == "ok" else fail).get(s, 0) + 1
    print(f"Wrote {args.out}")
    for s in sims:
        print(f"  {s:10s} ok={ok.get(s,0)} failed={fail.get(s,0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
