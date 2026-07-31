"""Per-model drill-down run table: per-engine execution (ran/error/absent)
plus the job's worst metric values; degrades gracefully without provenance.
"""
from viva_biomodels.lazy_viewer import _run_table

_INDEX = {"models": {"BIOMD1": {
    "jobs": {"utc1": {"engines": ["copasi", "tellurium"],
                      "matrix": {"copasi": {"tellurium": 0.0}},
                      "matrix_closeness": {"copasi": {"tellurium": 0.0}},
                      "max_nrmse": 0.0, "max_score": 0.0}},
    "runs": {"utc1": {"copasi": {"status": "ok", "error": ""},
                      "tellurium": {"status": "failed",
                                    "error": "RuntimeError: boom"}}}}}, "meta": {}}


def test_run_table_shows_execution_and_error():
    html = _run_table(_INDEX, "BIOMD1")
    assert "copasi" in html and "tellurium" in html
    assert "RuntimeError: boom" in html
    assert "utc1" in html


def test_run_table_salvaged_no_runs_does_not_crash():
    idx = {"models": {"B": {"jobs": {"utc1": {"engines": ["copasi"],
                                              "matrix": {}, "matrix_closeness": {}}}}}}
    html = _run_table(idx, "B")
    assert "copasi" in html


def test_run_table_escapes_error_html():
    idx = {"models": {"B": {"jobs": {"u": {"engines": ["c"]}},
                            "runs": {"u": {"c": {"status": "failed",
                                                 "error": "<script>x</script>"}}}}}}
    html = _run_table(idx, "B")
    assert "<script>" not in html and "&lt;script&gt;" in html
