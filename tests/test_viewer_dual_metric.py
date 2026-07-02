"""Lazy-viewer overview surfaces both metrics: nRMSE and closeness, on both
agreement axes (pbg↔pbg and pbg↔own-reference).
"""
from pbg_biomodels.lazy_viewer import _engine_analysis_closeness, _page

_INDEX = {"models": {"BIOMD1": {"has_series": True, "jobs": {"utc1": {
    "engines": ["copasi", "tellurium", "reference:copasi"],
    "matrix": {"copasi": {"tellurium": 0.0, "reference:copasi": 0.01},
               "tellurium": {"copasi": 0.0}, "reference:copasi": {"copasi": 0.01}},
    "matrix_closeness": {"copasi": {"tellurium": 0.0, "reference:copasi": 0.5},
                         "tellurium": {"copasi": 0.0},
                         "reference:copasi": {"copasi": 0.5}},
    "max_nrmse": 0.01, "bucket": "good",
    "max_score": 0.5, "closeness_bucket": "close",
    "n_ok": 2, "n_failed": 0, "kind": "utc"}}}}, "meta": {}}


def test_closeness_analysis_lens():
    j = _INDEX["models"]["BIOMD1"]["jobs"]["utc1"]
    a = _engine_analysis_closeness(j)
    assert a["pbg_pbg_max"] == 0.0          # copasi↔tellurium
    assert a["self_max"] == 0.5             # copasi↔reference:copasi


def test_page_has_closeness_columns():
    html = _page(_INDEX)
    assert "Close (≤1)" in html             # closeness bucket label rendered
    assert "cl pbg↔pbg" in html             # closeness column header
