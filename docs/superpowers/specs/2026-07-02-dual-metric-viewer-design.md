# Dual-metric comparison + run-provenance + expanded viewer — design (SP1+SP2)

**Date:** 2026-07-02
**Status:** approved (design), pending implementation plan
**Scope:** two coupled sub-projects of the larger "robust comparison service" goal.
SP1 (data layer): add the BioSimulations closeness-score metric alongside
mean-nRMSE and preserve per-engine run provenance in the index. SP2
(presentation): expand the lazy viewer to show all runs with execution and
agreement drill-down. **Out of scope:** SP3 (resource reorganization, export
hardening, hosting/CI, full frontend rebuild).

## Motivation

The comparison reports one metric (mean-nRMSE) and the viewer's drill-down only
loads the trajectory figure. Two gaps:

1. **Metric parity with the reference set.** The BioSimulations reference data
   was scored with a different metric (Lucian's `hdf5_compare.compare_arrays`) —
   a max-pointwise `np.allclose`-style ratio. Adding it lets us report agreement
   in the same terms the reference set uses.
2. **Run visibility.** Users can't see *which* engine × model runs failed (and
   why) or which agree vs diverge. The data partly exists — per-job
   `n_ok`/`n_failed` counts — but per-engine `status`/`error` is not surfaced,
   and `finalize_index` even drops it on fresh runs.

## Decisions (settled during brainstorming)

- **Two senses of "success", both surfaced:** *execution* (ran vs crashed/empty,
  with error text) and *agreement* (close vs diverged per metric). Independent
  lenses per (model × job × engine).
- **Two metrics, co-equal:** closeness score and mean-nRMSE shown side by side,
  each with its own buckets; the user picks which to sort/filter by. No single
  canonical verdict.
- **Graceful degradation:** the viewer shows rich per-engine detail when run
  provenance is present, and falls back to executed-vs-absent (inferred from
  series/matrix presence) on salvaged data that lacks `runs`.

## SP1 — Data layer

### Closeness metric (`comparison.py`)

Add, faithful to `biosimulations_runutils/.../hdf5_compare.py:38-62`:

```
atol = max(1e-3, 1e-5·max|a|, 1e-5·max|b|)
rtol = 1e-4
score = max( |a - b| / (atol + rtol·|b|) )      # over all aligned points
close = (score <= 1)                              # == np.allclose(a, b, rtol, atol)
NaN in either array  -> (False, 1e10)
FloatingPointError   -> (False, 1e12)
```

- `closeness_score(ys_a, ys_b) -> (bool, float)` operates on the aligned
  per-column value series `compare_two_engines` already extracts, so it applies
  uniformly to UTC, parameter-scan (both are axis-series), and steady-state
  (length-1) leaves. For a pair, the pair score is the **max** over shared
  observables (matching the source's max-reduction); `close` is the AND.
- Buckets: **Close (score ≤ 1) / Not close (score > 1) / Error (score ≥ 1e10)**.
  Faithful to the source (binary close/not-close); the raw max score is shown.

### Both metrics in the comparison result

`compare_n_engines` (and `compare_n_engines_steady_state`) keep every existing
key (`matrix`, `max_nrmse`, `bucket`, `pairs`, `worst_pair`, …) and add a
parallel closeness set:

```
matrix_closeness: {a: {b: score_or_None}}   # symmetric, diag None
max_score:        float | None              # worst (largest) pair score
closeness_bucket: str                       # bucket of the worst pair
worst_pair_closeness: [a, b] | None
```

Each entry in `pairs[a__b]` also carries `closeness_score` + `closeness_close`.
Purely additive — `BatchCompareStep` already calls `compare_n_engines`, so the
new fields flow through with no Step change.

### Preserve run provenance (`two_tier.py`)

- `finalize_index` keeps each model entry's `runs` (`{job: {engine: {status,
  error, runtime_s, n_points}}}`) instead of dropping it. `ray_runner` already
  attaches `entry["runs"] = diagnostics["runs"][bid]`.
- `write_model` records both metrics per job in the index entry
  (`max_nrmse`/`bucket` and `max_score`/`closeness_bucket`, plus the closeness
  matrix for the drill-down).

## SP2 — Viewer expansion (`lazy_viewer.py`)

The server, static, and browser-parquet exports share `_page`, so panels are
added once. New rendering is factored into helper functions (`_summary_panel`,
`_run_table`, …) to keep `_page` readable; a larger frontend restructure is
SP3.

### Overview tab

- Both metrics as co-equal, sortable columns on **both** agreement axes
  (pbg↔pbg and pbg↔ref) — extend `bco._engine_analysis` to compute the same
  max/self summaries from `matrix_closeness`.
- Filters: existing kind filter; new "has execution failures" and "diverged
  (either metric)" toggles.

### Summary tab (new — "all runs" at a glance)

- Per-engine **execution** success-rate bars: ran / crashed / absent across all
  models (from `runs`; falls back to has-data counts when `runs` absent).
- **Agreement** distributions: Close / Not-close counts per metric, and the
  nRMSE bucket histogram.

### Drill-down (expand a model row)

- A per-engine **run table** above the existing overlay figure:
  - *Execution*: ✓ ran / ✗ error (+ message from `runs`) / – absent.
  - *Agreement*: both metric values and close/not-close for each peer pair and
    vs each `reference:*`.
- Engines and status cells are clickable → filter the overview (e.g. click
  "simbio ✗" → all models where simbio failed).

## Data flow

```
SimulatorRunnerStep  -> results{bid:{job:{engine:leaf}}} + diagnostics.runs
BatchCompareStep     -> comparisons{bid:{job:{...nrmse... , ...closeness...}}}
two_tier.write_model -> series/<bid>.parquet + index entry (both metrics)
finalize_index       -> index.json (models[bid].jobs + models[bid].runs)
lazy_viewer          -> overview + summary + drill-down (execution + agreement)
```

## Error handling

- Closeness on empty/absent engine → excluded (same `present` filter as nRMSE).
- NaN/degenerate series → `(False, 1e10)` per the source; bucketed as Error.
- Salvaged index (no `runs`, no closeness matrix): summary/drill-down fall back
  to execution = has-data-vs-absent and hide error text; overview closeness
  columns show "—". Nothing crashes.

## Testing

- **Closeness metric:** matches `np.allclose` verdict on crafted arrays;
  identical → score 0 / close; shifted-beyond-tol → not close with expected
  score; NaN → `(False, 1e10)`; multi-observable pair takes the max.
- **compare_n_engines:** returns both matrices + per-pair closeness; all
  pre-existing keys unchanged (back-compat).
- **Index round-trip:** `write_model` + `finalize_index` preserve `runs` and both
  metrics; a salvaged index (no `runs`) still loads and renders.
- **Viewer:** `_page` overview has both metric columns; `_summary_panel` counts
  match a fixture index (executions + agreement); drill-down/run-table renders
  per-engine execution + agreement, including the salvaged-data fallback.

## Touch-point summary

| Layer | File | Change |
|---|---|---|
| Metric | `comparison.py` | `closeness_score`; both-metric `compare_n_engines` (+ SS) |
| Index | `two_tier.py` | preserve `runs`; store both metrics per job |
| Overview | `lazy_viewer.py` | dual-metric columns + failure/divergence filters |
| Summary | `lazy_viewer.py` | new per-engine execution + agreement summary tab |
| Drill-down | `lazy_viewer.py` | per-engine run table (execution + agreement), clickable filters |
