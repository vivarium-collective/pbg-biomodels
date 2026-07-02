"""All-runs Summary tab: per-engine execution + per-metric agreement,
using run provenance when present and degrading gracefully without it.
"""
from pbg_biomodels.lazy_viewer import _summary_stats, _summary_panel, _page

_INDEX = {"models": {
    "M1": {"jobs": {"utc1": {"engines": ["copasi", "tellurium"],
                             "bucket": "good", "closeness_bucket": "close",
                             "n_ok": 2, "n_failed": 0}},
           "runs": {"utc1": {"copasi": {"status": "ok"},
                             "tellurium": {"status": "failed"}}}},
    "M2": {"jobs": {"utc1": {"engines": ["copasi"],
                             "bucket": "large", "closeness_bucket": "not_close",
                             "n_ok": 1, "n_failed": 1}}},  # salvaged: no runs
}, "meta": {}}


def test_summary_execution_and_agreement():
    s = _summary_stats(_INDEX)
    assert s["engines"]["copasi"]["ran"] >= 1
    assert s["engines"]["tellurium"]["failed"] == 1
    assert s["agreement"]["closeness"]["close"] == 1
    assert s["agreement"]["closeness"]["not_close"] == 1
    assert s["agreement"]["nrmse"]["good"] == 1


def test_summary_panel_and_page_render():
    assert "Execution" in _summary_panel(_INDEX)
    assert "summary" in _page(_INDEX)       # the new tab/pane id


def test_execution_counts_distinct_models_not_job_rows():
    # copasi appears in TWO jobs of one model -> counts once, not twice.
    idx = {"models": {"M1": {"jobs": {
        "utc1": {"engines": ["copasi"], "bucket": "good", "closeness_bucket": "close"},
        "ss1": {"engines": ["copasi"], "bucket": "good", "closeness_bucket": "close"},
    }}}, "meta": {}}
    s = _summary_stats(idx)
    assert s["engines"]["copasi"]["ran"] == 1     # distinct model, not 2 job-rows
    assert s["provenance"] is False               # no runs -> salvaged


def test_provenance_flag_true_when_runs_present():
    s = _summary_stats(_INDEX)
    assert s["provenance"] is True                 # M1 carries runs
