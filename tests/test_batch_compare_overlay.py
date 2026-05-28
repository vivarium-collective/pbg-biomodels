"""`BatchCompareOverlay` is a Visualization that renders the full nested
results store into an HTML fragment. The smoke test here just checks the
fragment is non-empty and contains the biomodel id + simulator names —
the deep rendering is exercised in the end-to-end generator test.
"""
import pytest
from process_bigraph import allocate_core

from pbg_biomodels.visualizations.batch_compare_overlay import BatchCompareOverlay


def _utc(time, observables):
    return {"kind": "utc", "time": time, "observables": observables}


def test_overlay_renders_card_per_biomodel():
    viz = BatchCompareOverlay(
        config={
            "biomodel_ids": ["BIOMD0000000001", "BIOMD0000000002"],
            "title": "batch test",
        },
        core=allocate_core(),
    )
    out = viz.update({
        "results": {
            "BIOMD0000000001": {
                "copasi":    {"sim1": _utc([0.0, 1.0],
                                            {"A": [1.0, 0.5]})},
                "tellurium": {"sim1": _utc([0.0, 1.0],
                                            {"A": [1.0, 0.5]})},
            },
            "BIOMD0000000002": {
                "copasi":    {"sim1": _utc([0.0, 1.0],
                                            {"A": [2.0, 1.0]})},
            },
        },
        "comparisons": {
            "BIOMD0000000001": {"sim1": {
                "engines": ["copasi", "tellurium"], "pairs": {},
                "matrix": {}, "max_nrmse": 0.0,
                "worst_pair": None, "bucket": "good",
                "bucket_label": "Good (≤1%)",
            }},
            "BIOMD0000000002": {"sim1": {
                "engines": ["copasi"], "pairs": {},
                "matrix": {}, "max_nrmse": None,
                "worst_pair": None, "bucket": "none",
                "bucket_label": "No comparison",
            }},
        },
    })
    html = out["html"]
    assert isinstance(html, str) and html.strip()
    assert "BIOMD0000000001" in html
    assert "BIOMD0000000002" in html
    assert "copasi" in html
    assert "tellurium" in html
    assert "batch test" in html


def test_overlay_with_no_results_returns_placeholder():
    viz = BatchCompareOverlay(
        config={"biomodel_ids": []},
        core=allocate_core(),
    )
    out = viz.update({"results": {}, "comparisons": {}})
    assert "No biomodels" in out["html"]
