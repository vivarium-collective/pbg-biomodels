"""Lazy-viewer overview surfaces both metrics: nRMSE and closeness, on both
agreement axes (pbg↔pbg and pbg↔own-reference).
"""
from viva_biomodels.lazy_viewer import _engine_analysis_closeness, _page

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


def test_every_overview_column_is_sortable():
    html = _page(_INDEX)
    # all 11 overview columns (0..10) must have a sortBy click handler
    for col in range(11):
        assert f"sortBy({col}," in html, f"column {col} not sortable"
    # numeric metric columns sort by their data attribute; counts sort numeric
    assert "sortBy(4,'d:pbg')" in html
    assert "sortBy(9,'n')" in html and "sortBy(10,'n')" in html


def test_sort_captures_detail_row_before_moving():
    # regression: appending the row first makes r.nextElementSibling null, so
    # appendChild(null) throws and the whole sort silently aborts. The detail
    # sibling must be captured BEFORE the row is re-appended.
    html = _page(_INDEX)
    assert "body.appendChild(r.nextElementSibling)" not in html
    assert "var d=r.nextElementSibling;body.appendChild(r);if(d)body.appendChild(d);" in html
