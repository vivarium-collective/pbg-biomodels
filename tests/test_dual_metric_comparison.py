"""compare_n_engines (+ steady-state) carry the closeness metric alongside
nRMSE, without disturbing any existing key.
"""
from pbg_biomodels.comparison import (
    compare_two_engines,
    compare_n_engines,
    compare_two_engines_steady_state,
    compare_n_engines_steady_state,
)

_UTC_A = {"columns": ["A"], "values": [[1.0], [2.0], [3.0]], "time": [0, 1, 2]}
_UTC_B = {"columns": ["A"], "values": [[1.0], [2.0], [3.0]], "time": [0, 1, 2]}
_UTC_C = {"columns": ["A"], "values": [[1.0], [2.0], [9.0]], "time": [0, 1, 2]}


def test_pair_carries_both_metrics():
    r = compare_two_engines(_UTC_A, _UTC_B, "copasi", "tellurium")
    assert r["mean_nrmse"] == 0.0
    assert r["closeness_score"] == 0.0
    assert r["closeness_close"] is True


def test_n_engines_has_closeness_matrix_and_backcompat():
    r = compare_n_engines({"copasi": _UTC_A, "tellurium": _UTC_B, "simbio": _UTC_C})
    assert set(r) >= {"engines", "pairs", "matrix", "max_nrmse", "bucket"}
    assert "matrix_closeness" in r and "max_score" in r and "closeness_bucket" in r
    assert r["matrix_closeness"]["copasi"]["tellurium"] == 0.0
    assert r["matrix_closeness"]["copasi"]["simbio"] > 1.0
    assert r["closeness_bucket"] == "not_close"


def test_all_close_bucket():
    r = compare_n_engines({"copasi": _UTC_A, "tellurium": _UTC_B})
    assert r["closeness_bucket"] == "close"


def test_steady_state_pair_and_matrix():
    pr = compare_two_engines_steady_state({"A": 1.0}, {"A": 1.0}, "c", "t")
    assert pr["closeness_score"] == 0.0 and pr["closeness_close"] is True
    r = compare_n_engines_steady_state(
        {"c": {"A": 1.0}, "t": {"A": 1.0}, "s": {"A": 50.0}})
    assert "matrix_closeness" in r and r["closeness_bucket"] == "not_close"
    assert r["matrix_closeness"]["c"]["t"] == 0.0
