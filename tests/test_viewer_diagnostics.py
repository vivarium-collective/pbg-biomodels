"""Diagnostics tab + enriched Summary/Cross-engine tabs in the lazy viewer.

Everything is derived from the two-tier index alone (no run provenance needed):
a dataset overview, per-engine coverage by task kind with reference pairing, a
divergence roster, a within-pbg closeness matrix, and a runtime/error table that
degrades to a clear note when no provenance was captured.
"""
from viva_biomodels.lazy_viewer import _diagnostics_stats, _page

# One diverging UTC job (nRMSE 0.5, closeness 137) with a reference, and one
# clean steady-state job introducing a second engine (amici, steady-state only).
_INDEX = {"models": {"M1": {"has_series": True, "jobs": {
    "utc0": {
        "engines": ["copasi", "tellurium", "reference:copasi"],
        "matrix": {"copasi": {"tellurium": 0.5, "reference:copasi": 0.01},
                   "tellurium": {"copasi": 0.5},
                   "reference:copasi": {"copasi": 0.01}},
        "matrix_closeness": {"copasi": {"tellurium": 137.4, "reference:copasi": 0.3},
                             "tellurium": {"copasi": 137.4},
                             "reference:copasi": {"copasi": 0.3}},
        "max_nrmse": 0.5, "bucket": "large", "max_score": 137.4,
        "closeness_bucket": "not_close", "n_ok": 2, "n_failed": 0, "kind": "utc"},
    "ss0": {
        "engines": ["copasi", "amici"],
        "matrix": {"copasi": {"amici": 0.0}, "amici": {"copasi": 0.0}},
        "matrix_closeness": {"copasi": {"amici": 0.0}, "amici": {"copasi": 0.0}},
        "max_nrmse": 0.0, "bucket": "good", "max_score": 0.0,
        "closeness_bucket": "close", "n_ok": 2, "n_failed": 0,
        "kind": "steady_state"}}}},
    "meta": {"salvaged_from_parquet": True,
             "metrics_backfilled_from_parquet": True}}


def test_diagnostics_stats_coverage_and_divergence():
    s = _diagnostics_stats(_INDEX)
    assert s["n_models"] == 1 and s["n_jobs"] == 2
    assert s["kinds"] == {"utc": 1, "steady_state": 1, "repeated_task": 0}
    assert s["ref_models"] == 1
    # copasi appears in both kinds; amici only in steady_state
    assert len(s["cov"]["copasi"]["any"]) == 1
    assert "utc" not in s["cov"]["amici"] and "steady_state" in s["cov"]["amici"]
    # copasi has a reference:copasi pairing; tellurium/amici do not
    assert len(s["ref_paired"].get("copasi", ())) == 1
    assert "tellurium" not in s["ref_paired"]
    # only the utc0 job diverges (nRMSE 0.5 > 0.10)
    assert [d["job"] for d in s["diverged"]] == ["utc0"]


def test_diagnostics_tab_rendered():
    html = _page(_INDEX, static=True)
    assert "showTab(event,'diagnostics')" in html   # tab button
    assert '<div id="diagnostics"' in html          # pane
    for section in ("Dataset overview", "Engine coverage", "Divergence roster",
                    "Per-simulation runtime", "ref-paired"):
        assert section in html, f"missing diagnostics section: {section}"


def test_salvaged_dataset_shows_provenance_note_not_runtime_table():
    html = _page(_INDEX, static=True)
    # no runtime provenance -> explicit note, not a fabricated table
    assert "No per-run provenance" in html


def test_cross_engine_has_closeness_matrix():
    html = _page(_INDEX, static=True)
    assert "Within-pbg closeness" in html


def test_runtime_table_rendered_when_provenance_present():
    idx = {"models": {"M1": {"has_series": True,
        "runs": {"utc0": {"copasi": {"runtime_s": 1.25, "status": "ok"},
                          "tellurium": {"runtime_s": 0.0, "status": "failed",
                                        "error": "boom"}}},
        "jobs": {"utc0": {
            "engines": ["copasi", "tellurium"],
            "matrix": {"copasi": {"tellurium": 0.0}, "tellurium": {"copasi": 0.0}},
            "matrix_closeness": {"copasi": {"tellurium": 0.0},
                                 "tellurium": {"copasi": 0.0}},
            "max_nrmse": 0.0, "bucket": "good", "max_score": 0.0,
            "closeness_bucket": "close", "n_ok": 1, "n_failed": 1,
            "kind": "utc"}}}}, "meta": {}}
    html = _page(idx, static=True)
    assert "1.2500" in html and "boom" in html      # runtime + error surfaced
    assert "No per-run provenance" not in html
