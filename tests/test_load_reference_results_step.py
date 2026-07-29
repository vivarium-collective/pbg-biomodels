"""`LoadReferenceResultsStep` reads the BioSimulators reference dataset and
writes each engine's timeseries into `results[bid][job]["reference:<engine>"]`,
plus a `ref_grid[bid][job]` sample-count used to drive the live runners onto
the same time grid.
"""
from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
from process_bigraph import allocate_core

from viva_biomodels.steps.load_reference_results import LoadReferenceResultsStep


def _write_reports_h5(path: Path, *, labels=("Time", "A", "B"), n_time=5):
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
    return data


def _models(job_name="myjob", n_points=5):
    return {
        "BIOMD0000000001": {
            "sbml_path": "/tmp/x.xml",
            "sedml_jobs": [
                {"name": job_name, "kind": "utc", "time": 10.0, "n_points": n_points}
            ],
        }
    }


def test_single_job_writes_reference_engines_under_live_job_key(tmp_path):
    root = tmp_path / "dataset"
    bid = "BIOMD0000000001"
    _write_reports_h5(root / bid / "copasi" / "4.45.296" / "results" / "outputs" / "reports.h5")
    _write_reports_h5(root / bid / "tellurium" / "2.2.10" / "outputs" / "reports.h5")

    step = LoadReferenceResultsStep(
        config={"reference_results_dir": str(root)}, core=allocate_core()
    )
    out = step.update({"models": _models(job_name="myjob")})

    job = out["results"][bid]["myjob"]
    # Both engines present, keyed `reference:<engine>`, under the LIVE job key.
    assert "reference:copasi" in job
    assert "reference:tellurium" in job
    # Leaf is the standard results shape (reserved `time` + observables).
    leaf = job["reference:copasi"]
    assert "time" in leaf and leaf["A"] and leaf["B"]
    # ref_grid carries the reference sample count for grid alignment.
    assert out["ref_grid"][bid]["myjob"] == 5


def test_reference_simulators_config_restricts_engines(tmp_path):
    root = tmp_path / "dataset"
    bid = "BIOMD0000000001"
    _write_reports_h5(root / bid / "copasi" / "4.45.296" / "results" / "outputs" / "reports.h5")
    _write_reports_h5(root / bid / "tellurium" / "2.2.10" / "outputs" / "reports.h5")

    step = LoadReferenceResultsStep(
        config={"reference_results_dir": str(root), "reference_simulators": ["copasi"]},
        core=allocate_core(),
    )
    out = step.update({"models": _models(job_name="myjob")})

    job = out["results"][bid]["myjob"]
    assert "reference:copasi" in job
    assert "reference:tellurium" not in job


def test_missing_model_dir_is_skipped_not_an_error(tmp_path):
    root = tmp_path / "dataset"  # exists but empty — no model subdirs
    root.mkdir()
    step = LoadReferenceResultsStep(
        config={"reference_results_dir": str(root)}, core=allocate_core()
    )
    out = step.update({"models": _models()})
    # No engines found → empty per-bid maps, no ref_grid entries, no exception.
    assert out["results"]["BIOMD0000000001"] == {}
    assert out["ref_grid"]["BIOMD0000000001"] == {}
