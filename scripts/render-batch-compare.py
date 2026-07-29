#!/usr/bin/env python3
"""Render the batch-compare viewer HTML from a saved results store.

Reproducible regeneration of the BioModels batch-comparison app. Reads the
nested results/comparisons/diagnostics store (the same payload the
`batch-compare-biomodels` composite emits, persisted to
``.pbg/last_batch_results.json``) and renders it through
``BatchCompareOverlay`` into a single self-contained HTML page.

Usage:
    python scripts/render-batch-compare.py \
        [--results .pbg/last_batch_results.json] \
        [--out reports/batch_compare_first10.html] \
        [--title "BioModels batch comparison — first 10 (COPASI vs Tellurium vs SimBio)"]

The viewer gives each simulator a stable color across every figure (see
``BatchCompareOverlay._SIMULATOR_COLORS``).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from viva_biomodels.visualizations.batch_compare_overlay import BatchCompareOverlay

_DEFAULT_TITLE = (
    "BioModels batch comparison — first 10 (COPASI vs Tellurium vs SimBio vs AMICI)"
)


def render(results_path: Path, out_path: Path, title: str) -> Path:
    store = json.loads(results_path.read_text(encoding="utf-8"))
    ids = store.get("ids") or list((store.get("results") or {}).keys())

    # update() only reads self.config + the state dict, so we can skip the
    # process-bigraph Step constructor (which would require a registry core).
    viz = BatchCompareOverlay.__new__(BatchCompareOverlay)
    viz.config = {"title": title, "biomodel_ids": ids}
    fragment = viz.update({
        "results":     store.get("results") or {},
        "comparisons": store.get("comparisons") or {},
        "diagnostics": store.get("diagnostics") or {},
    })["html"]

    page = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title></head><body>{fragment}</body></html>"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    return out_path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", type=Path,
                    default=root / ".pbg" / "last_batch_results.json")
    ap.add_argument("--out", type=Path,
                    default=root / "reports" / "batch_compare_first10.html")
    ap.add_argument("--title", default=_DEFAULT_TITLE)
    args = ap.parse_args()

    out = render(args.results, args.out, args.title)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
