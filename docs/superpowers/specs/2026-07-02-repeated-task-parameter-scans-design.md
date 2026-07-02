# Repeated-task (parameter-scan) support — design

**Date:** 2026-07-02
**Status:** approved (design), pending implementation plan
**Scope:** add a third comparison task kind, `repeated_task`, to the BioModels
multi-simulator comparison — derived faithfully from each model's SED-ML
`repeatedTask`, reduced to a response curve, compared across the live engines
*and* the BioSimulators reference results.

## Motivation

The batch comparison currently handles two SED-ML task kinds — uniform time
course (`utc`) and `steady_state`. Many curated BioModels also ship
`repeatedTask` elements, overwhelmingly **1-D parameter scans**: sweep one model
parameter over a range and observe how the system responds. These are dropped
today:

- `run_biomodels.extract_all_simulations` iterates SED-ML *simulations* and
  skips anything that isn't UTC/steady-state with a `UserWarning`
  (`run_biomodels.py:228`).
- `reference_results._find_utc_report` selects only a 2-D
  `[n_dataset, n_timepoint]` report with a `Time` row; a repeatedTask report
  (which carries a scan dimension) is skipped, and
  `LoadReferenceResultsStep` logs "no UTC report; skipping"
  (`load_reference_results.py:78`).

So neither our live engines nor the reference set contribute scan results today.
This work closes both gaps.

## Key decisions (settled during brainstorming)

1. **Source:** faithful reproduction of the model's own SED-ML `repeatedTask`.
   We do not synthesize scans.
2. **Reduction:** reduce each scan to a **response curve** — one summary value
   per scan point per observable. For a UTC subtask the summary is the
   **endpoint** (last output row); for a steady-state subtask it is the
   steady-state value. We do not retain the full per-scan-point trajectory in
   v1.
3. **Scope:** **1-D scans only** — a single `uniformRange` or `vectorRange`
   with constant `setValue` target(s) resolving to one swept attribute. Nested
   repeatedTasks, `functionalRange`, and multi-target scans are detected and
   **skipped with a `UserWarning`** (the existing graceful-skip pattern).
4. **Representation:** "scan-as-axis" (Approach A). A scan leaf is structurally
   a UTC leaf with the `time` axis replaced by a reserved `scan` axis, so the
   existing nRMSE comparison and the UTC overlay figure are reused with the
   x-axis relabeled to the swept parameter.
5. **Parameter application:** mutate the SBML `model_source` per scan point via
   libSBML (clone + set the target attribute) and hand the modified source to
   the *existing* UTC/steady-state simulator step. No simulator wrapper changes;
   uniform across all five engines because they all consume `model_source`.

## Leaf representation

`result_leaf.py` gains a third reserved axis key and a three-way classifier:

```
TIME_KEY = "time"     # utc            — observables sampled over time
SCAN_KEY = "scan"     # repeated_task  — observables sampled over the scan param
# (neither)           # steady_state   — length-1 observable lists
```

A scan leaf looks like:

```python
{"scan": [v1, v2, …, vn],          # the scan parameter values (ordered)
 "<obs A>": [a1, a2, …, an],        # obs A endpoint at each scan point
 "<obs B>": [b1, b2, …, bn]}
```

New/changed accessors:

- `is_scan(leaf) -> bool` — `SCAN_KEY in leaf`.
- `kind_of(leaf)` — returns `"utc"` if `is_utc`, else `"repeated_task"` if
  `is_scan`, else `"steady_state"`. **Precedence:** a leaf never carries both
  `time` and `scan` (the reduction removes the time axis), but if both are
  present `utc` wins and a warning is emitted (defensive).
- `axis_of(leaf) -> (name, values)` — returns `("time", …)`,
  `("scan", …)`, or `("", [])`. Used by the comparison and viewer so the axis
  is handled generically.
- `to_numeric_result` — extended to treat `scan` as the axis exactly like
  `time`, so downstream math is axis-agnostic.

## Derivation — `run_biomodels.py`

New `extract_repeated_tasks(sed_doc) -> list[dict]` walks SED-ML **tasks**
(`getNumTasks`/`getTask`), not simulations:

For each task where `task.getTypeCode()` is `SEDML_TASK_REPEATEDTASK`:

1. **Range** — resolve the master range (`task.getRangeId()` → the referenced
   `SedRange`):
   - `uniformRange` → expand `[start, end]` with `numberOfPoints` on the
     declared scale (linear/log) into an ordered value list.
   - `vectorRange` → the explicit value list.
   - `functionalRange` or a nested range reference → **skip** the task with a
     `UserWarning` (out of v1 scope).
2. **setValue** — require exactly one `SedSetValue`. Resolve its `target`
   (XPath into SBML, e.g.
   `/sbml/model/listOfParameters/parameter[@id='k1']/@value`) to a
   `(sbml_element_id, attribute)` pair via a small XPath resolver
   (`_resolve_setvalue_target`). `>1` setValue, or an unresolvable/ non-constant
   target (a `math` expression referencing the range) → **skip** with a
   `UserWarning`.
3. **Subtask** — resolve the single `SedSubTask` → its referenced `SedTask` →
   that task's `SedSimulation`. Classify the subtask simulation as `utc` or
   `steady_state` using the same predicates as `extract_all_simulations`.
   Multiple subtasks → **skip** with a `UserWarning`.

Returns entries of the form:

```python
{"name": task_id, "kind": "repeated_task",
 "param_id": sbml_element_id, "param_attr": attribute,
 "scan_values": [v1, …, vn],
 "subtask": {"kind": "utc"|"steady_state", "time": …, "n_points": …}}
```

`extract_all_simulations` is unchanged; the runner calls the new extractor in
addition and merges the job lists.

## Runner reduction

New helper `mutate_sbml(model_source, element_id, attribute, value) -> str`
(libSBML: read model, clone, set the attribute on the identified element, write
to a temp SBML path / string). libSBML is already a dependency.

For each repeated-task job, for each scan value `v`:

1. `src_v = mutate_sbml(model_source, param_id, param_attr, v)`
2. Run the subtask via the **existing** per-engine UTC/steady-state step on
   `src_v` → a `numeric_result`.
3. Reduce: UTC → last row (endpoint) per observable; steady-state → the SS
   value per observable.

Assemble the leaf `{scan: scan_values, <obs>: [reduced per v]}`. Runs
identically for every engine because the mutation happens on `model_source`
upstream of the simulator wrappers. A scan point that fails to simulate
contributes `NaN` at that index (curve stays full-length; comparison already
tolerates NaN via `BUCKET_THRESHOLDS`).

## Comparison — `comparison.py`

No new metric. A response curve is an ordered series over the scan axis, so
`compare_n_engines` (the UTC path) already computes the right nRMSE once `scan`
is treated as the axis via `axis_of`/`to_numeric_result`. The same
`BUCKET_THRESHOLDS` vocabulary applies, keeping the divergence buckets shared
across all three kinds. Two engines' curves must be sampled on the same scan
values to compare — they are, because both come from the same SED-ML range.

## Reference-side — `reference_results.py` + `load_reference_results.py`

BioSimulators stores a repeatedTask report in `reports.h5` with a scan
dimension (a 3-D `[n_dataset, n_scan, n_timepoint]` dataset for a UTC subtask,
or 2-D `[n_dataset, n_scan]` for a steady-state subtask). Add:

- `read_reference_scan_leaf(h5_path, scan_values) -> leaf` — locate the
  repeatedTask report (a SedReport whose data rank exceeds the UTC 2-D case, or
  whose SED-ML output derives from the repeatedTask), reduce along the time axis
  to the **endpoint per scan index** (mirroring the live reduction), and map the
  observable rows to the response-curve leaf. The `scan` axis values are taken
  from the SED-ML range (`scan_values`), so reference and live align 1:1 by
  index.
- `LoadReferenceResultsStep` — when the job kind is `repeated_task`, call the
  scan reader instead of the UTC reader and write the leaf under
  `results[bid][<job>]["reference:<engine>"]`, exactly like the UTC path. When a
  reference engine has no repeatedTask report, it is simply absent for that job
  (already handled — engines with no leaf are dropped from the matrix).

`read_reference_leaf`/`_find_utc_report` are unchanged for UTC jobs.

## Persistence + viewer — `two_tier.py`, `lazy_viewer.py`

- `series_table` — write the scan axis into the existing `time` parquet column
  (non-NaN, so it is not mistaken for steady-state). The column stays named
  `time` (a generic axis column); the per-job `kind` in the index disambiguates.
  Generalize the `is_ss = "time" not in leaf` branch to use `axis_of` so a scan
  leaf's axis is emitted rather than NaN-filled.
- `write_model` / `_job_kind` — record `kind: "repeated_task"` and the swept
  `param_id` in the index job entry (for the x-axis label).
- `lazy_viewer._parquet_leaves_aligned` — relabel the reconstituted axis by the
  job kind: `time` → `scan` for a `repeated_task` job so
  `result_leaf.is_scan` is true on round-trip.
- `lazy_viewer._figure_for` — a `repeated_task` job reuses
  `bco._utc_overlay_figure` with the x-axis title set to `param_id` (the swept
  parameter), not "time".
- The viewer's kind filter gains a `repeated_task` option alongside `utc` and
  `steady_state` (both the server-rendered `<select>` and the client filter).

## Non-goals (v1)

- No full per-scan-point trajectory retention or drill-down (Approach C).
- No nested/2-D scans, `functionalRange`, or multi-target `setValue`
  (skipped with a warning).
- No synthesized scans for models that lack a `repeatedTask`.
- Reference comparison only where the BioSimulators reference set actually
  contains a repeatedTask report for that model/engine.

## Testing

Unit:

1. `extract_repeated_tasks` on a fixture SED-ML with a `uniformRange` +
   single `setValue` → expected `param_id`, `scan_values`, subtask kind; and a
   fixture with a nested/functional range → skipped with a warning.
2. `mutate_sbml` sets the correct attribute on the correct element and leaves
   others untouched (round-trip read-back).
3. `result_leaf` classification + parquet round-trip: a scan leaf survives
   `series_table` → read back → `is_scan` true, axis values preserved.
4. Comparison reuse: two identical scan curves score 0 nRMSE; a shifted curve
   lands in the expected bucket; a curve with a NaN scan point is tolerated.
5. Reference scan reader: a fixture `reports.h5` with a scan-shaped report
   reduces to the expected response curve aligned to `scan_values`.

Integration:

6. End-to-end run on 1–2 real BioModels known to ship a `repeatedTask`,
   verifying the job appears in `index.json` with `kind: "repeated_task"`, a
   parquet series, a cross-engine matrix, and (where present) a `reference:*`
   column, and renders in the lazy viewer as a response curve.

## Touch-point summary

| Layer | File | Change |
|---|---|---|
| Derivation | `run_biomodels.py` | `extract_repeated_tasks`, XPath target resolver |
| Reduction | runner / `steps` | `mutate_sbml`, per-scan-point loop + endpoint reduction |
| Leaf | `result_leaf.py` | `SCAN_KEY`, `is_scan`, 3-way `kind_of`, `axis_of` |
| Comparison | `comparison.py` | reuse UTC path via `axis_of` (no new metric) |
| Reference | `reference_results.py`, `steps/load_reference_results.py` | `read_reference_scan_leaf`, kind-aware dispatch |
| Persist+view | `two_tier.py`, `lazy_viewer.py` | axis-generic parquet, `param_id` in index, viewer x-axis + kind filter |
