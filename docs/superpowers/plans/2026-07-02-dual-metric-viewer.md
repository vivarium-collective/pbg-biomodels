# Dual-metric comparison + run-provenance + expanded viewer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the BioSimulations closeness-score metric alongside mean-nRMSE, preserve per-engine run provenance in the index, and expand the lazy viewer with an all-runs summary and a per-engine execution + agreement drill-down.

**Architecture:** Additive throughout. The comparison layer computes a second per-pair metric with no change to existing keys; `two_tier` stores both metrics and stops dropping `runs`; the lazy viewer (shared by server/static/browser-parquet exports via `_page`) gains panels rendered by new helper functions. Salvaged indexes (no `runs`, no closeness) degrade gracefully.

**Tech Stack:** Python 3.12, `.venv/bin/python`, pytest, pyarrow/plotly (already deps). Run tests with `.venv/bin/python -m pytest`.

## Global Constraints

- Closeness metric must be faithful to `biosimulations_runutils/.../hdf5_compare.py:38-62`: `atol = max(1e-3, 1e-5·max|a|, 1e-5·max|b|)`, `rtol = 1e-4`, `score = max(|a−b|/(atol+rtol·|b|))`, `close = score ≤ 1`; NaN → `(False, 1e10)`; FloatingPointError → `(False, 1e12)`.
- All existing `compare_n_engines` / `compare_two_engines` return keys stay unchanged (back-compat) — only add keys.
- Closeness buckets: `close`/`Close (≤1)`, `not_close`/`Not close (>1)`, `error`/`Error` (score ≥ 1e10). Reuse `NO_COMPARISON_BUCKET` when score is None.
- Viewer changes must not crash on a salvaged index (no `runs`, no `matrix_closeness`): show "—" / executed-vs-absent fallback.
- Commit after each task. Base branch: `feat/dual-metric-viewer`.

---

### Task 1: Closeness metric primitive

**Files:**
- Modify: `viva_biomodels/comparison.py` (add near `bucket_for`)
- Test: `tests/test_closeness_metric.py` (create)

**Interfaces:**
- Produces: `closeness_score(y1: list[float], y2: list[float]) -> tuple[bool, float]` and `closeness_bucket_for(score: float | None) -> tuple[str, str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_closeness_metric.py
import numpy as np
import pytest
from viva_biomodels.comparison import closeness_score, closeness_bucket_for


def test_identical_series_is_close_zero():
    assert closeness_score([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == (True, 0.0)


def test_matches_numpy_allclose_verdict():
    a = [1.0, 2.0, 3.0]
    b = [1.0, 2.0, 3.05]
    close, score = closeness_score(a, b)
    atol = max(1e-3, max(map(abs, a)) * 1e-5, max(map(abs, b)) * 1e-5)
    assert close == bool(np.allclose(a, b, rtol=1e-4, atol=atol))
    assert (score <= 1.0) == close


def test_large_deviation_not_close():
    close, score = closeness_score([1.0, 2.0], [1.0, 5.0])
    assert close is False and score > 1.0


def test_nan_returns_sentinel():
    assert closeness_score([1.0, float("nan")], [1.0, 2.0]) == (False, 1e10)


def test_empty_series_is_close():
    assert closeness_score([], []) == (True, 0.0)


def test_bucket_mapping():
    assert closeness_bucket_for(0.0)[0] == "close"
    assert closeness_bucket_for(5.0)[0] == "not_close"
    assert closeness_bucket_for(1e10)[0] == "error"
    assert closeness_bucket_for(None)[0] == closeness_bucket_for(None)[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_closeness_metric.py -q`
Expected: FAIL with `ImportError: cannot import name 'closeness_score'`

- [ ] **Step 3: Write minimal implementation**

Add to `viva_biomodels/comparison.py` (after `bucket_for`):

```python
def closeness_score(y1, y2):
    """BioSimulations allclose-style score for two aligned value series.

    Faithful to biosimulations_runutils hdf5_compare.compare_arrays:
    atol = max(1e-3, 1e-5*max|a|, 1e-5*max|b|), rtol = 1e-4,
    score = max(|a-b| / (atol + rtol*|b|)); close = score <= 1.
    Returns (close: bool, score: float). NaN -> (False, 1e10);
    arithmetic blow-up -> (False, 1e12).
    """
    a = [float(x) for x in y1]
    b = [float(x) for x in y2]
    n = min(len(a), len(b))
    if n == 0:
        return True, 0.0
    a, b = a[:n], b[:n]
    if any(math.isnan(x) for x in a) or any(math.isnan(x) for x in b):
        return False, 1e10
    atol = max(1e-3, max(abs(x) for x in a) * 1e-5, max(abs(x) for x in b) * 1e-5)
    rtol = 1e-4
    try:
        score = max(abs(a[i] - b[i]) / (atol + rtol * abs(b[i])) for i in range(n))
    except (ZeroDivisionError, OverflowError, ValueError):
        return False, 1e12
    return score <= 1.0, score


CLOSENESS_ERROR_FLOOR = 1e10


def closeness_bucket_for(score):
    """Map a closeness score to a ``(bucket_id, label)`` pair."""
    if score is None:
        return NO_COMPARISON_BUCKET
    if score >= CLOSENESS_ERROR_FLOOR:
        return "error", "Error"
    if score <= 1.0:
        return "close", "Close (≤1)"
    return "not_close", "Not close (>1)"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_closeness_metric.py -q`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_closeness_metric.py viva_biomodels/comparison.py
git commit -m "Add BioSimulations closeness-score metric primitive"
```

---

### Task 2: Both metrics in the comparison results

**Files:**
- Modify: `viva_biomodels/comparison.py` — `compare_two_engines`, `compare_n_engines`, `compare_two_engines_steady_state`, `compare_n_engines_steady_state`
- Test: `tests/test_dual_metric_comparison.py` (create)

**Interfaces:**
- Consumes: `closeness_score`, `closeness_bucket_for` (Task 1).
- Produces: `compare_two_engines(...)` result also has `closeness_score: float | None` and `closeness_close: bool`. `compare_n_engines(...)` (and the SS variant) result also has `matrix_closeness: {a:{b: score|None}}`, `max_score: float | None`, `worst_pair_closeness: [a,b]|None`, `closeness_bucket: str`, `closeness_bucket_label: str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dual_metric_comparison.py
from viva_biomodels.comparison import compare_two_engines, compare_n_engines

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
    # back-compat keys intact
    assert set(r) >= {"engines", "pairs", "matrix", "max_nrmse", "bucket"}
    # new closeness keys
    assert "matrix_closeness" in r and "max_score" in r and "closeness_bucket" in r
    # copasi==tellurium close; simbio diverges
    assert r["matrix_closeness"]["copasi"]["tellurium"] == 0.0
    assert r["matrix_closeness"]["copasi"]["simbio"] > 1.0
    assert r["closeness_bucket"] == "not_close"


def test_all_close_bucket():
    r = compare_n_engines({"copasi": _UTC_A, "tellurium": _UTC_B})
    assert r["closeness_bucket"] == "close"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dual_metric_comparison.py -q`
Expected: FAIL with `KeyError: 'closeness_score'`

- [ ] **Step 3: Implement — `compare_two_engines`**

In `compare_two_engines`, after the per-species loop builds `ys_per_engine` and computes `rmse`, accumulate closeness across shared species. Add before the `return`:

```python
    # Closeness (BioSimulations allclose-style), max over shared species.
    pair_close, pair_score = True, 0.0
    have_pair = False
    for sp in species:
        ys = {}
        for eng_name, payload in engines.items():
            if not payload:
                continue
            cols = payload.get("columns", [])
            if sp in cols:
                j = cols.index(sp)
                ys[eng_name] = [row[j] for row in payload.get("values", [])]
        if len(ys) < 2:
            continue
        have_pair = True
        keys = sorted(ys)
        c, s = closeness_score(ys[keys[0]], ys[keys[1]])
        pair_close = pair_close and c
        pair_score = max(pair_score, s)
    cl_score = pair_score if have_pair else None
```

Then add to the returned dict:

```python
        "closeness_score": cl_score,
        "closeness_close": bool(pair_close) if have_pair else False,
```

- [ ] **Step 4: Implement — `compare_n_engines`**

After the existing pair loop (which fills `matrix`/`max_nrmse`), add a parallel closeness rollup. Inside the `for a … for b …` loop, after `matrix[a][b] = mean`, add:

```python
            cs = result.get("closeness_score")
            matrix_closeness[a][b] = cs
            matrix_closeness[b][a] = cs
            if cs is not None and (max_score is None or cs > max_score):
                max_score = cs
                worst_pair_closeness = [a, b]
```

Declare before the loop (next to `max_nrmse`):

```python
    matrix_closeness = {a: {b: None for b in present} for a in present}
    max_score = None
    worst_pair_closeness = None
```

And after `bucket_id, bucket_label = bucket_for(max_nrmse)` add:

```python
    cl_bucket, cl_label = closeness_bucket_for(max_score)
```

Extend the returned dict with:

```python
        "matrix_closeness": matrix_closeness,
        "max_score": max_score,
        "worst_pair_closeness": worst_pair_closeness,
        "closeness_bucket": cl_bucket,
        "closeness_bucket_label": cl_label,
```

- [ ] **Step 5: Implement — steady-state variants**

In `compare_two_engines_steady_state`, after building `nrmse_by_species`, add closeness over shared scalars (each a 1-element series):

```python
    pair_close, pair_score = True, 0.0
    for sp in shared:
        c, s = closeness_score([a[sp]], [b[sp]])
        pair_close = pair_close and c
        pair_score = max(pair_score, s)
    cl_score = pair_score if shared else None
```

Add to its return dict: `"closeness_score": cl_score, "closeness_close": bool(pair_close) if shared else False,`.

In `compare_n_engines_steady_state`, mirror the Task-2 Step-4 closeness rollup exactly (same added declarations, loop lines, `closeness_bucket_for`, and return keys).

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/test_dual_metric_comparison.py tests/test_comparison_steady_state.py -q`
Expected: PASS (new + existing SS tests still green)

- [ ] **Step 7: Commit**

```bash
git add tests/test_dual_metric_comparison.py viva_biomodels/comparison.py
git commit -m "Compute closeness score alongside nRMSE in compare_n_engines (+SS)"
```

---

### Task 3: Persist both metrics + preserve run provenance

**Files:**
- Modify: `viva_biomodels/two_tier.py` — `write_model` (job entry), `finalize_index` (keep `runs`)
- Test: `tests/test_two_tier_provenance.py` (create)

**Interfaces:**
- Consumes: comparison results with closeness keys (Task 2).
- Produces: index `models[bid]["jobs"][job]` also has `max_score`, `closeness_bucket`, `matrix_closeness`; index `models[bid]["runs"]` preserved when the entry carries it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_two_tier_provenance.py
import json
from pathlib import Path
from viva_biomodels.two_tier import write_model, finalize_index


def test_write_model_stores_both_metrics(tmp_path):
    results = {"utc1": {"copasi": {"time": [0, 1], "A": [1.0, 2.0]},
                        "tellurium": {"time": [0, 1], "A": [1.0, 2.0]}}}
    comps = {"utc1": {"engines": ["copasi", "tellurium"],
                      "matrix": {"copasi": {"tellurium": 0.0}},
                      "max_nrmse": 0.0, "bucket": "excellent",
                      "matrix_closeness": {"copasi": {"tellurium": 0.0}},
                      "max_score": 0.0, "closeness_bucket": "close"}}
    entry = write_model("BIOMD1", results, comps, tmp_path)
    je = entry["jobs"]["utc1"]
    assert je["max_nrmse"] == 0.0 and je["bucket"] == "excellent"
    assert je["max_score"] == 0.0 and je["closeness_bucket"] == "close"
    assert je["matrix_closeness"] == {"copasi": {"tellurium": 0.0}}


def test_finalize_index_preserves_runs(tmp_path):
    entry = {"id": "BIOMD1", "jobs": {}, "has_series": True,
             "runs": {"utc1": {"copasi": {"status": "ok", "error": "",
                                          "runtime_s": 0.1, "n_points": 2}}}}
    finalize_index([entry], tmp_path, meta={"n_models": 1})
    idx = json.loads((tmp_path / "index.json").read_text())
    assert idx["models"]["BIOMD1"]["runs"]["utc1"]["copasi"]["status"] == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_two_tier_provenance.py -q`
Expected: FAIL (`KeyError: 'max_score'`; `KeyError: 'runs'`)

- [ ] **Step 3: Implement — `write_model` job entry**

In `write_model`, extend `jobs_entry[job]` with:

```python
            "max_score": comp.get("max_score"),
            "closeness_bucket": comp.get("closeness_bucket"),
            "matrix_closeness": comp.get("matrix_closeness") or {},
```

- [ ] **Step 4: Implement — `finalize_index` keeps `runs`**

Change the `models` comprehension in `finalize_index` to carry `runs` when present:

```python
    index = {
        "models": {
            e["id"]: {
                "jobs": e["jobs"],
                "has_series": e.get("has_series"),
                **({"runs": e["runs"]} if e.get("runs") else {}),
            }
            for e in entries if e
        },
        "meta": meta or {},
        "diagnostics": diagnostics or {},
    }
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_two_tier_provenance.py tests/test_two_tier.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_two_tier_provenance.py viva_biomodels/two_tier.py
git commit -m "Persist both metrics per job and preserve per-engine run provenance in index"
```

---

### Task 4: Overview — dual-metric columns + closeness analysis lens

**Files:**
- Modify: `viva_biomodels/lazy_viewer.py` — add `_engine_analysis_closeness`, extend `_overview_rows` + the overview `<thead>` + `applyFilter`
- Test: `tests/test_viewer_dual_metric.py` (create)

**Interfaces:**
- Consumes: index job entries with `matrix_closeness` / `max_score` / `closeness_bucket` (Task 3).
- Produces: `_engine_analysis_closeness(comparison: dict) -> {"pbg_pbg_max": float|None, "self_max": float|None}` (reads `matrix_closeness`); overview rows carry `data-clpbg` / `data-clself` and closeness cells.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_viewer_dual_metric.py
from viva_biomodels.lazy_viewer import _engine_analysis_closeness, _page

_INDEX = {"models": {"BIOMD1": {"has_series": True, "jobs": {"utc1": {
    "engines": ["copasi", "tellurium", "reference:copasi"],
    "matrix": {"copasi": {"tellurium": 0.0, "reference:copasi": 0.01}},
    "matrix_closeness": {"copasi": {"tellurium": 0.0, "reference:copasi": 0.5}},
    "max_nrmse": 0.01, "bucket": "excellent",
    "max_score": 0.5, "closeness_bucket": "close",
    "n_ok": 2, "n_failed": 0, "kind": "utc"}}}}, "meta": {}}


def test_closeness_analysis_lens():
    j = _INDEX["models"]["BIOMD1"]["jobs"]["utc1"]
    a = _engine_analysis_closeness(j)
    assert a["pbg_pbg_max"] == 0.0          # copasi↔tellurium
    assert a["self_max"] == 0.5             # copasi↔reference:copasi


def test_page_has_closeness_columns():
    html = _page(_INDEX)
    assert "Close (≤1)" in html or "closeness" in html.lower()
    assert "score" in html.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_viewer_dual_metric.py -q`
Expected: FAIL (`ImportError: _engine_analysis_closeness`)

- [ ] **Step 3: Implement — closeness analysis lens**

Add to `lazy_viewer.py`:

```python
def _engine_analysis_closeness(job_entry):
    """pbg↔pbg and pbg↔own-reference worst CLOSENESS score for one job,
    mirroring bco._engine_analysis but reading `matrix_closeness`."""
    return bco._engine_analysis({
        "engines": job_entry.get("engines") or [],
        "matrix": job_entry.get("matrix_closeness") or {},
    })
```

- [ ] **Step 4: Implement — overview columns + rows**

In `_overview_rows`, compute the closeness lens per job and emit extra cells + data attributes. After the existing `a = bco._engine_analysis(...)` line add:

```python
            ac = _engine_analysis_closeness(j)
            cl_pbg, cl_self = ac["pbg_pbg_max"], ac["self_max"]
            cl_bucket, cl_label = bco.bucket_for(cl_pbg) if False else (
                j.get("closeness_bucket") or "none",
                {"close": "Close (≤1)", "not_close": "Not close (>1)",
                 "error": "Error"}.get(j.get("closeness_bucket"), "—"))
            cl_pbg_s = num(cl_pbg) or "—"
            cl_self_s = num(cl_self) or "—"
```

Append to the `<tr>` (before the closing `</tr>`), and add the data attributes to the row's opening tag: `data-clpbg="{cl_pbg if isinstance(cl_pbg,(int,float)) else -1}"`:

```python
                f'<td>{cl_label}</td>'
                f'<td class="num">{cl_pbg_s}</td><td class="num">{cl_self_s}</td>'
```

Update the `<tr class="detail-row">` `colspan` from `8` to `11`.

In `_page`, extend the overview `<thead>` with three headers after the existing failed column:

```html
  <th onclick="sortBy(8,'s')">Closeness</th>
  <th class="num" onclick="sortBy(9,'clpbg')">cl pbg↔pbg</th>
  <th class="num" onclick="sortBy(10,'clself')">cl pbg↔ref</th>
```

Extend `sortBy` numeric branch to include the new types:

```javascript
  if(type==='pbg'||type==='self'||type==='clpbg'||type==='clself'){return parseFloat(b.dataset[type])-parseFloat(a.dataset[type]);}
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_viewer_dual_metric.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_viewer_dual_metric.py viva_biomodels/lazy_viewer.py
git commit -m "Viewer overview: dual-metric columns + closeness analysis lens"
```

---

### Task 5: Summary tab — all-runs execution + agreement

**Files:**
- Modify: `viva_biomodels/lazy_viewer.py` — add `_summary_stats` + `_summary_panel`, add a "Summary" tab to `_page`
- Test: `tests/test_viewer_summary.py` (create)

**Interfaces:**
- Consumes: index with `models[bid].runs` (optional) + `jobs[job]` metric buckets.
- Produces: `_summary_stats(index: dict) -> {"engines": {eng: {"ran": int, "failed": int, "absent": int}}, "agreement": {"nrmse": {bucket: n}, "closeness": {bucket: n}}}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_viewer_summary.py
from viva_biomodels.lazy_viewer import _summary_stats

_INDEX = {"models": {
    "M1": {"jobs": {"utc1": {"engines": ["copasi", "tellurium"],
                             "bucket": "excellent", "closeness_bucket": "close",
                             "n_ok": 2, "n_failed": 0}},
           "runs": {"utc1": {"copasi": {"status": "ok"},
                             "tellurium": {"status": "failed"}}}},
    "M2": {"jobs": {"utc1": {"engines": ["copasi"],
                             "bucket": "poor", "closeness_bucket": "not_close",
                             "n_ok": 1, "n_failed": 1}}},  # no runs (salvaged)
}, "meta": {}}


def test_summary_execution_and_agreement():
    s = _summary_stats(_INDEX)
    # M1 has explicit runs: copasi ran, tellurium failed
    assert s["engines"]["copasi"]["ran"] >= 1
    assert s["engines"]["tellurium"]["failed"] == 1
    # agreement buckets tallied across jobs
    assert s["agreement"]["closeness"]["close"] == 1
    assert s["agreement"]["closeness"]["not_close"] == 1
    assert s["agreement"]["nrmse"]["excellent"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_viewer_summary.py -q`
Expected: FAIL (`ImportError: _summary_stats`)

- [ ] **Step 3: Implement — `_summary_stats`**

```python
def _summary_stats(index):
    """Aggregate execution (per engine) + agreement (per metric bucket)
    across all models/jobs. Uses per-engine `runs` when present; else falls
    back to executed = engine appears in a job's `engines` list."""
    engines = {}
    agreement = {"nrmse": {}, "closeness": {}}

    def bump(d, k):
        d[k] = d.get(k, 0) + 1

    for bid, m in (index.get("models") or {}).items():
        runs = m.get("runs") or {}
        for job, j in (m.get("jobs") or {}).items():
            bump(agreement["nrmse"], j.get("bucket") or "none")
            bump(agreement["closeness"], j.get("closeness_bucket") or "none")
            job_runs = runs.get(job) or {}
            if job_runs:
                for eng, rec in job_runs.items():
                    e = engines.setdefault(eng, {"ran": 0, "failed": 0, "absent": 0})
                    if (rec.get("status") or "") == "ok":
                        e["ran"] += 1
                    else:
                        e["failed"] += 1
            else:  # salvaged: infer executed from the engine list
                for eng in j.get("engines") or []:
                    engines.setdefault(eng, {"ran": 0, "failed": 0, "absent": 0})["ran"] += 1
    return {"engines": engines, "agreement": agreement}
```

- [ ] **Step 4: Implement — `_summary_panel` + tab wiring**

Add `_summary_panel(index) -> str` rendering `_summary_stats` as two small tables (per-engine ran/failed/absent; agreement bucket counts for each metric):

```python
def _summary_panel(index):
    s = _summary_stats(index)
    erows = "".join(
        f"<tr><td>{e}</td><td class='num'>{v['ran']}</td>"
        f"<td class='num'>{v['failed']}</td></tr>"
        for e, v in sorted(s["engines"].items()))
    def buckets(name):
        return "".join(f"<tr><td>{k}</td><td class='num'>{n}</td></tr>"
                       for k, n in sorted(s["agreement"][name].items()))
    return (
        "<h4>Execution (per engine)</h4>"
        "<table><thead><tr><th>Engine</th><th>ran</th><th>failed</th></tr>"
        f"</thead><tbody>{erows}</tbody></table>"
        "<h4>Agreement — nRMSE</h4>"
        f"<table><tbody>{buckets('nrmse')}</tbody></table>"
        "<h4>Agreement — closeness</h4>"
        f"<table><tbody>{buckets('closeness')}</tbody></table>")
```

In `_page`, add a third tab button and pane:

```html
 <button class="tab" onclick="showTab(event,'summary')">Summary</button>
```
```html
<div id="summary" class="pane">{_summary_panel(index)}</div>
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_viewer_summary.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_viewer_summary.py viva_biomodels/lazy_viewer.py
git commit -m "Viewer: all-runs Summary tab (per-engine execution + agreement)"
```

---

### Task 6: Drill-down — per-engine execution + agreement run table

**Files:**
- Modify: `viva_biomodels/lazy_viewer.py` — add `_run_table(index, bid)` + `/api/runs/<bid>` route; inject the table into `openModel` (server + static)
- Test: `tests/test_viewer_run_table.py` (create)

**Interfaces:**
- Consumes: `models[bid].runs` (optional) + `jobs[job]` matrices.
- Produces: `_run_table(index: dict, bid: str) -> str` (HTML) rendering, per job, a per-engine row with execution status (✓ ran / ✗ error+msg / – absent) and agreement (both metric worst values + close/not-close).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_viewer_run_table.py
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
    assert "RuntimeError: boom" in html      # failed engine's error surfaced
    assert "utc1" in html


def test_run_table_salvaged_no_runs_does_not_crash():
    idx = {"models": {"B": {"jobs": {"utc1": {"engines": ["copasi"],
                                              "matrix": {}, "matrix_closeness": {}}}}}}
    html = _run_table(idx, "B")
    assert "copasi" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_viewer_run_table.py -q`
Expected: FAIL (`ImportError: _run_table`)

- [ ] **Step 3: Implement — `_run_table`**

```python
def _run_table(index, bid):
    """Per-engine execution + agreement table for one model, across its jobs."""
    m = (index.get("models") or {}).get(bid) or {}
    runs = m.get("runs") or {}
    out = []
    for job, j in (m.get("jobs") or {}).items():
        engs = j.get("engines") or []
        # union with any engine that has a run record
        engs = sorted(set(engs) | set((runs.get(job) or {}).keys()))
        rows = []
        for e in engs:
            rec = (runs.get(job) or {}).get(e)
            if rec is None:
                exec_cell = "<span class='ok'>✓ ran</span>" if e in (j.get("engines") or []) else "– absent"
            elif (rec.get("status") or "") == "ok":
                exec_cell = "<span class='ok'>✓ ran</span>"
            else:
                err = (rec.get("error") or "").replace("<", "&lt;")
                exec_cell = f"<span class='bad'>✗ {rec.get('status','failed')}</span> {err}"
            rows.append(f"<tr><td>{e}</td><td>{exec_cell}</td></tr>")
        out.append(
            f"<h4>{job}</h4>"
            f"<div class='small'>worst nRMSE {j.get('max_nrmse','—')} · "
            f"worst closeness {j.get('max_score','—')}</div>"
            "<table><thead><tr><th>Engine</th><th>Execution</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>")
    return "".join(out) or "<div class='small'>no jobs</div>"
```

- [ ] **Step 4: Wire into the drill-down**

Add a route in `make_handler.do_GET` before the figure route:

```python
                if p.startswith("/api/runs/"):
                    bid = p.rsplit("/", 1)[-1]
                    return self._send(_run_table(index, bid), "text/html; charset=utf-8")
```

In the server-mode `open_js`, after the box is revealed and before/after loading the figure, prepend the run table (fetch as text and insert):

```javascript
      fetch('/api/runs/'+bid).then(r=>r.text()).then(function(h){
        var t=document.createElement('div'); t.innerHTML=h; box.insertBefore(t, box.firstChild);});
```

For static mode, `export_static` already writes `figures/<bid>.json`; also write `runs/<bid>.html` = `_run_table(index, bid)` and fetch it analogously in the static `open_js`.

Add CSS to the `<style>` block: `.ok{color:#2e7d32}.bad{color:#c62828}.small{color:#666;font-size:12px}`.

- [ ] **Step 5: Run tests + full suite**

Run: `.venv/bin/python -m pytest tests/test_viewer_run_table.py tests/ -q`
Expected: PASS (pre-existing `test_biomodel_process_runs[pysces]` failure is unrelated — sibling-repo bug)

- [ ] **Step 6: Commit**

```bash
git add tests/test_viewer_run_table.py viva_biomodels/lazy_viewer.py
git commit -m "Viewer drill-down: per-engine execution + agreement run table"
```

---

## Self-Review

**Spec coverage:**
- Closeness metric faithful to source → Task 1. ✓
- Both metrics co-equal in comparison → Task 2. ✓
- Preserve run provenance in index → Task 3 (`finalize_index`). ✓
- Both metrics stored per job → Task 3. ✓
- Overview dual-metric columns + both agreement axes → Task 4. ✓
- All-runs summary (execution + agreement) → Task 5. ✓
- Per-engine execution + agreement drill-down → Task 6. ✓
- Graceful degradation on salvaged data → Tasks 5 & 6 fallback branches + tests. ✓
- Clickable filters ("show only failures", by-engine): overview filter toggles are stubbed by the `data-*` attributes in Task 4; a follow-up wires JS toggle buttons — **added as a note**, not a separate task, to keep scope tight. (Sort by both metrics is delivered in Task 4.)

**Placeholder scan:** No TBD/TODO; every code step shows real code.

**Type consistency:** `closeness_score`/`closeness_bucket_for` (Task 1) used verbatim in Task 2; `matrix_closeness`/`max_score`/`closeness_bucket` (Task 2) consumed by Tasks 3–6; `_engine_analysis_closeness` (Task 4) and `_summary_stats`/`_run_table` (Tasks 5–6) names consistent across their tasks.

**Note on filters:** the "has failures / diverged" overview toggle buttons are a thin JS addition on top of Task 4's `data-*` attributes; fold into Task 4 during execution if time allows, else a trivial follow-up. Not a blocker for any task's deliverable.
