"""``LoadReferenceResultsStep`` — fold BioSimulators reference results into the
batch-compare ``results`` store.

For each biomodel in ``models``, this Step locates the single UTC SED-ML job
and, for every reference engine present on disk (or the configured subset),
reads that engine's ``reports.h5`` into a results leaf and writes it to
``results[bid][<job>]["reference:<engine>"]`` — alongside the live simulators,
so ``BatchCompareStep`` folds it into the all-pairs nRMSE automatically.

It also emits ``ref_grid[bid][<job>] = <n_samples>``: the reference report's
sample count, which :class:`~viva_biomodels.steps.simulator_runner.SimulatorRunnerStep`
reads to drive the live engines onto the same time grid (so the index-aligned
comparison math is meaningful).

Reference is opt-in: the batch generator only wires this Step when
``reference_results_dir`` is set, so the default composite is unchanged.

**Single-job rule.** A model with exactly one UTC job maps its reference 1:1
under that job key. A model with several UTC jobs is a SED-ML the 1:1 rule
can't disambiguate: a warning is emitted and its reference engines are written
under the report's own id (visible in ``results`` but not cross-compared with
the live engines).
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any, ClassVar, Dict, List

from process_bigraph import Step

from viva_biomodels import reference_results
from viva_biomodels.result_leaf import TIME_KEY


class LoadReferenceResultsStep(Step):
    config_schema: ClassVar[Dict[str, Any]] = {
        "reference_results_dir": {"_type": "string", "_default": ""},
        "reference_simulators": {"_type": "list[string]", "_default": []},
    }

    def inputs(self) -> Dict[str, str]:
        return {"models": "map[biomodel_jobs]"}

    def outputs(self) -> Dict[str, str]:
        # `tree` for the same reason the runner uses it: new keys appear at every
        # nesting level (bid + job + `reference:<engine>`), so the tree apply
        # deep-merges these leaves alongside the live runners' slices.
        return {"results": "tree", "ref_grid": "tree", "diagnostics": "tree"}

    def update(self, state: Dict[str, Any]) -> Dict[str, Any]:
        root = self.config.get("reference_results_dir") or ""
        only = list(self.config.get("reference_simulators") or [])

        results: Dict[str, Dict[str, Any]] = {}
        ref_grid: Dict[str, Dict[str, int]] = {}
        provenance: Dict[str, Dict[str, Any]] = {}

        if not root:
            return {"results": results, "ref_grid": ref_grid,
                    "diagnostics": {"reference": provenance}}

        for bid, model in (state.get("models") or {}).items():
            results[bid] = {}
            ref_grid[bid] = {}
            jobs = list((model or {}).get("sedml_jobs") or [])
            scan_jobs = [j for j in jobs if j.get("kind") == "repeated_task"]
            has_utc = any(j.get("kind") == "utc" for j in jobs)
            job_key = self._reference_job_key(bid, model) if has_utc else None
            if job_key is None and not scan_jobs:
                continue

            engines = only or reference_results.discover_reference_engines(root, bid)
            for engine in engines:
                h5 = reference_results.resolve_engine_h5(root, bid, engine)
                if h5 is None:
                    continue

                # UTC reference (1:1 with the single UTC job).
                if job_key is not None:
                    leaf = reference_results.read_reference_leaf(h5)
                    if not leaf:
                        warnings.warn(
                            f"LoadReferenceResultsStep: {bid}/{engine} reports.h5 "
                            f"had no UTC report; skipping",
                            stacklevel=2,
                        )
                    else:
                        results[bid].setdefault(job_key, {})[
                            f"reference:{engine}"] = leaf
                        ref_grid[bid][job_key] = len(leaf.get(TIME_KEY) or [])
                        provenance.setdefault(bid, {})[engine] = {
                            "path": str(h5),
                            "version": h5.parent.parent.parent.name
                            if "results" in h5.parts else h5.parent.parent.name,
                            "n_samples": len(leaf.get(TIME_KEY) or []),
                        }

                # Parameter-scan references (1:1 with each repeated_task job).
                for sj in scan_jobs:
                    sleaf = reference_results.read_reference_scan_leaf(
                        h5, sj.get("scan_values"))
                    # a scan leaf with only the axis carries no observables.
                    if len(sleaf) <= 1:
                        continue
                    results[bid].setdefault(sj["name"], {})[
                        f"reference:{engine}"] = sleaf

        return {"results": results, "ref_grid": ref_grid,
                "diagnostics": {"reference": provenance}}

    def _reference_job_key(self, bid: str, model: Any) -> str | None:
        """The `results` bucket key the reference leaves go under.

        Single UTC job → that job's name (1:1, cross-compared). Several UTC
        jobs → warn; caller still loads them but they won't align with live.
        Zero UTC jobs → None (nothing to attach to).
        """
        jobs: List[Dict[str, Any]] = list((model or {}).get("sedml_jobs") or [])
        utc = [j for j in jobs if j.get("kind") == "utc"]
        if len(utc) == 1:
            return utc[0].get("name") or "sim"
        if len(utc) == 0:
            warnings.warn(
                f"LoadReferenceResultsStep: {bid} has no UTC job; skipping reference",
                stacklevel=2,
            )
            return None
        warnings.warn(
            f"LoadReferenceResultsStep: {bid} has {len(utc)} UTC jobs; the 1:1 rule "
            f"can't align reference — loading under report ids (uncompared)",
            stacklevel=2,
        )
        # Multi-job: fall back to a stable bucket so the data is at least visible.
        return "reference"
