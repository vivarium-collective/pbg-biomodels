"""`BatchCompareOverlay` is a Visualization that renders the full nested
results store into an HTML fragment. The smoke test here just checks the
fragment is non-empty and contains the biomodel id + simulator names —
the deep rendering is exercised in the end-to-end generator test.
"""
import pytest
from process_bigraph import allocate_core

from pbg_biomodels.visualizations.batch_compare_overlay import BatchCompareOverlay


def _utc(time, observables):
    """A UTC results leaf: flat map[observable -> timeseries] with reserved time."""
    return {"time": list(time), **observables}


def test_overlay_renders_card_per_biomodel():
    viz = BatchCompareOverlay(
        config={
            "biomodel_ids": ["BIOMD0000000001", "BIOMD0000000002"],
            "title": "batch test",
        },
        core=allocate_core(),
    )
    out = viz.update({
        # New nesting: results[bid][sedml_job][sim] = leaf.
        # BIOMD...0002/sim1 has tellurium FAILED (empty leaf).
        "results": {
            "BIOMD0000000001": {
                "sim1": {
                    "copasi":    _utc([0.0, 1.0], {"A": [1.0, 0.5]}),
                    "tellurium": _utc([0.0, 1.0], {"A": [1.0, 0.5]}),
                },
            },
            "BIOMD0000000002": {
                "sim1": {
                    "copasi":    _utc([0.0, 1.0], {"A": [2.0, 1.0]}),
                    "tellurium": {},  # failed run -> empty leaf
                },
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
    # Overview tab exists with a SED-ML job column and a failed-simulators column.
    assert "Overview" in html
    assert "SED-ML job" in html
    assert "Simulators failed" in html
    # The sedml job id appears as a row value.
    assert "sim1" in html


def test_overlay_renders_diagnostics_tab():
    viz = BatchCompareOverlay(
        config={"biomodel_ids": ["BIOMD0000000001"], "title": "diag test"},
        core=allocate_core(),
    )
    out = viz.update({
        "results": {"BIOMD0000000001": {"sim1": {"copasi": _utc([0.0, 1.0], {"A": [1.0, 0.5]})}}},
        "comparisons": {},
        "diagnostics": {
            "meta": {"host": "testbox", "platform": "macOS-test", "python": "3.12.0"},
            "provenance": {"copasi": {
                "simulator": "copasi", "lib_version": "0.86",
                "wrapper": "pbg-copasi", "wrapper_version": "0.1.0",
                "wrapper_git": {"commit": "c5604b7", "dirty": False},
                "started_utc": "2026-06-03T20:00:00+00:00", "total_runtime_s": 0.123,
            }},
            "runs": {"BIOMD0000000001": {"sim1": {"copasi": {
                "runtime_s": 0.0123, "status": "ok", "error": "", "n_points": 50,
            }}}},
        },
    })
    html = out["html"]
    assert "Diagnostics" in html
    assert "testbox" in html           # host
    assert "c5604b7" in html           # wrapper git commit
    assert "Per-simulation runtime" in html
    assert "2026-06-03T20:00:00+00:00" in html  # when


def test_simulator_colors_are_consistent_across_figures():
    """A given simulator must keep the same line color in every figure, across
    every biomodel — copasi/tellurium/simbio resolve to their canonical hues."""
    import json as _json

    from pbg_biomodels.visualizations import batch_compare_overlay as bco

    viz = BatchCompareOverlay(
        config={"biomodel_ids": ["BIOMD0000000001", "BIOMD0000000002"]},
        core=allocate_core(),
    )
    out = viz.update({
        "results": {
            # Different simulator iteration order per biomodel: if colors were
            # assigned by trace index they would diverge between the two cards.
            "BIOMD0000000001": {"sim1": {
                "copasi":    _utc([0.0, 1.0], {"A": [1.0, 0.5]}),
                "tellurium": _utc([0.0, 1.0], {"A": [1.0, 0.4]}),
                "simbio":    _utc([0.0, 1.0], {"A": [1.0, 0.6]}),
            }},
            "BIOMD0000000002": {"sim1": {
                "simbio":    _utc([0.0, 1.0], {"A": [2.0, 1.6]}),
                "tellurium": _utc([0.0, 1.0], {"A": [2.0, 1.4]}),
                "copasi":    _utc([0.0, 1.0], {"A": [2.0, 1.5]}),
            }},
        },
        "comparisons": {},
    })
    html = out["html"]

    # Pull every embedded figure blob and collect each simulator's line colors.
    colors: dict = {}
    # The assignment form is `window.__batchFigures["BID"] = {...}`; the leading
    # quote distinguishes it from the unquoted JS reads in the toggle script.
    marker = 'window.__batchFigures["'
    i = 0
    while (j := html.find(marker, i)) >= 0:
        k = html.find("{", html.find("=", j))
        depth, end = 0, k
        while end < len(html):
            if html[end] == "{":
                depth += 1
            elif html[end] == "}":
                depth -= 1
                if depth == 0:
                    break
            end += 1
        i = end + 1
        for fig in _json.loads(html[k:end + 1]).values():
            for tr in fig.get("data", []):
                name, line = tr.get("name"), (tr.get("line") or {})
                if name and line.get("color"):
                    colors.setdefault(name, set()).add(line["color"])

    assert colors, "no colored traces were embedded"
    for name, hues in colors.items():
        assert len(hues) == 1, f"{name} used multiple colors: {sorted(hues)}"
    assert colors["copasi"] == {bco._SIMULATOR_COLORS["copasi"]}
    assert colors["tellurium"] == {bco._SIMULATOR_COLORS["tellurium"]}
    assert colors["simbio"] == {bco._SIMULATOR_COLORS["simbio"]}


def test_overlay_with_no_results_returns_placeholder():
    viz = BatchCompareOverlay(
        config={"biomodel_ids": []},
        core=allocate_core(),
    )
    out = viz.update({"results": {}, "comparisons": {}})
    assert "No biomodels" in out["html"]
