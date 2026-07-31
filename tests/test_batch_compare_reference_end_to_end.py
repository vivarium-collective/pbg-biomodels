"""End-to-end with reference results ON: build the batch composite with a
`reference_results_dir`, stubbed LoadBiomodelStep (single UTC job) + stubbed
runner adapters, run it, and assert the reference engines land in `results`
and `comparisons` as `reference:<engine>`, and that the live engines were
sampled on the reference time grid (driven via `ref_grid`).
"""
from pathlib import Path
from typing import Any, ClassVar, Dict

import h5py
import numpy as np
from process_bigraph import Step

_REF_N_TIME = 5  # reference report sample count → should drive live n_points


def _write_reports_h5(path: Path, *, labels=("Time", "A", "B"), n_time=_REF_N_TIME):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.array(
        [[float(r) + float(c) for c in range(n_time)] for r in range(len(labels))],
        dtype="float64",
    )
    with h5py.File(path, "w") as f:
        grp = f.create_group("BIOMD0000000001_url.sedml")
        ds = grp.create_dataset("autogen_report_for_task1", data=data)
        ds.attrs["_type"] = "SedReport"
        ds.attrs["sedmlDataSetLabels"] = list(labels)


class _StubLoad(Step):
    """Replaces LoadBiomodelStep — single UTC job, so the 1:1 rule applies."""

    config_schema: ClassVar[Dict[str, Any]] = {}

    def inputs(self):
        return {"biomodel_id": "string"}

    def outputs(self):
        return {"sbml_path": "string", "sedml_jobs": "list[tree]",
                "time": "float", "n_points": "integer"}

    def update(self, state):
        bid = state.get("biomodel_id") or ""
        return {
            "sbml_path": f"/tmp/{bid}.xml",
            # job n_points=3 — the reference grid (5) must override it.
            "sedml_jobs": [{"name": "sim1", "kind": "utc", "time": 1.0, "n_points": 3}],
            "time": 1.0, "n_points": 3,
        }


class _StubUTC:
    """Runner UTC adapter stub — echoes n_points so we can prove grid drive."""
    def __init__(self, config=None, core=None):
        pass

    def update(self, state):
        n = int(state.get("n_points") or 0)
        return {"result": {
            "time": [float(i) for i in range(n)],
            "columns": ["A", "B"],
            "values": [[1.0, 0.0] for _ in range(n)],
        }}


def test_reference_engines_join_results_and_comparison(tmp_path, monkeypatch):
    from process_bigraph import Composite, gather_emitter_results

    from viva_biomodels import register_types
    from viva_biomodels.core import build_core
    from viva_superpowers.composite_generator import _REGISTRY, build_generator
    import viva_biomodels.composites.batch_compare_biomodels  # noqa: F401
    import viva_biomodels.steps.simulator_runner as runner_mod

    # Reference dataset with two engines for BIOMD0000000001.
    root = tmp_path / "dataset"
    bid = "BIOMD0000000001"
    _write_reports_h5(root / bid / "copasi" / "4.45.296" / "results" / "outputs" / "reports.h5")
    _write_reports_h5(root / bid / "tellurium" / "2.2.10" / "outputs" / "reports.h5")

    monkeypatch.setattr(runner_mod, "_UTC_CLASS_FOR", lambda name: _StubUTC)

    core = register_types(build_core())
    core.register_link("viva_biomodels.steps.load_biomodel.LoadBiomodelStep", _StubLoad)

    entry = next(e for e in _REGISTRY.values() if e.name == "batch-compare-biomodels")
    doc = build_generator(entry, overrides={
        "biomodel_ids": [bid],
        "simulators": ["copasi", "tellurium"],
        "reference_results_dir": str(root),
    })
    composite = Composite(doc, core=core)
    composite.run(0.0)

    snap = (gather_emitter_results(composite).get(("emitter",)) or [{}])[-1]
    job = snap["results"][bid]["sim1"]

    # Live engines AND reference engines share the sim1 bucket.
    assert set(job) == {"copasi", "tellurium", "reference:copasi", "reference:tellurium"}
    # Reference leaf carries the reserved time + observables.
    assert job["reference:copasi"]["time"] == [0.0, 1.0, 2.0, 3.0, 4.0]

    # Live engines were sampled on the reference grid (n_points 3 → 5).
    assert len(job["copasi"]["time"]) == _REF_N_TIME
    diag = snap["diagnostics"]["runs"][bid]["sim1"]
    assert diag["copasi"]["n_points"] == _REF_N_TIME

    # All four engines enter the all-pairs comparison.
    cmp = snap["comparisons"][bid]["sim1"]
    assert set(cmp["engines"]) == {"copasi", "tellurium", "reference:copasi", "reference:tellurium"}
