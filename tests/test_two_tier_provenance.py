"""two_tier stores both metrics per job and preserves per-engine run
provenance in index.json (finalize_index no longer drops `runs`).
"""
import json

import pytest

pytest.importorskip("pyarrow")  # two_tier is optional (no parquet in base CI)

from viva_biomodels.two_tier import write_model, finalize_index


def test_write_model_stores_both_metrics(tmp_path):
    results = {"utc1": {"copasi": {"time": [0, 1], "A": [1.0, 2.0]},
                        "tellurium": {"time": [0, 1], "A": [1.0, 2.0]}}}
    comps = {"utc1": {"engines": ["copasi", "tellurium"],
                      "matrix": {"copasi": {"tellurium": 0.0}},
                      "max_nrmse": 0.0, "bucket": "good",
                      "matrix_closeness": {"copasi": {"tellurium": 0.0}},
                      "max_score": 0.0, "closeness_bucket": "close"}}
    entry = write_model("BIOMD1", results, comps, tmp_path)
    je = entry["jobs"]["utc1"]
    assert je["max_nrmse"] == 0.0 and je["bucket"] == "good"
    assert je["max_score"] == 0.0 and je["closeness_bucket"] == "close"
    assert je["matrix_closeness"] == {"copasi": {"tellurium": 0.0}}


def test_finalize_index_preserves_runs(tmp_path):
    entry = {"id": "BIOMD1", "jobs": {}, "has_series": True,
             "runs": {"utc1": {"copasi": {"status": "ok", "error": "",
                                          "runtime_s": 0.1, "n_points": 2}}}}
    finalize_index([entry], tmp_path, meta={"n_models": 1})
    idx = json.loads((tmp_path / "index.json").read_text())
    assert idx["models"]["BIOMD1"]["runs"]["utc1"]["copasi"]["status"] == "ok"


def test_finalize_index_omits_runs_when_absent(tmp_path):
    entry = {"id": "BIOMD2", "jobs": {}, "has_series": False}
    finalize_index([entry], tmp_path, meta={})
    idx = json.loads((tmp_path / "index.json").read_text())
    assert "runs" not in idx["models"]["BIOMD2"]
