# corpus_comparison

A compact, git-friendly COPASI + Tellurium time-course dataset for the full
BioModels comparison corpus, committed here so other repos can read the
results directly without depending on the (large, uncommitted) raw run
output.

## Provenance

Derived from `out/compare_all_1054/` in the `viva-biomodels` workspace — the
output of the full compare-all sweep across the BioModels corpus (892
models with usable series data, out of 1054 attempted). That directory is
scratch: multi-hundred-MB per-model `series/*.parquet` files plus
`index.json` metrics, not committed anywhere.

`scripts/build_corpus_dataset.py` builds this dataset from that source:

1. For each `series/<biomodel_id>.parquet` (tidy, columns `[job, engine,
   variable, time, value]`), keep only rows where `engine` is `copasi` or
   `tellurium` (the two direct, non-reference engines used for the
   corpus-wide comparison). Models with neither engine are skipped.
2. Downsample each `(biomodel_id, job, engine, variable)` series to at most
   100 points by even stride (first/last timepoint always kept). This is
   the main size lever — raw series can run to thousands of points per
   variable.
3. Concatenate everything into one tidy parquet:
   `corpus_timecourse.parquet`.
4. Pull the copasi<->tellurium pairwise comparison out of
   `out/compare_all_1054/index.json`'s per-job `matrix` field (which holds
   all-engine-pairs NRMSE) into a small `corpus_metrics.json` summary, one
   entry per `(biomodel_id, job)` where both engines are present.

Regenerate with:

```
.venv/bin/python scripts/build_corpus_dataset.py \
    --source /path/to/compare_all_1054 --out datasets/corpus_comparison
```

If the resulting parquet exceeds ~15 MB at 100 points/series, the script
automatically retries at 60 points/series and prints a note.

## Files

- `corpus_timecourse.parquet` — tidy time-course data.
  Columns: `biomodel_id` (str/category), `job` (category — one of
  `auto_ten_seconds`, `auto_steady_state`), `engine` (category — `copasi`
  or `tellurium`), `variable` (category), `time` (float32), `value`
  (float32). Downsampled to <= 100 rows per `(biomodel_id, job, engine,
  variable)` group.
- `corpus_metrics.json` — nested dict:
  `{biomodel_id: {job: {"copasi__tellurium": {mean_nrmse, bucket, n_shared}}}}`.
  - `mean_nrmse`: the copasi-vs-tellurium NRMSE for that model/job, taken
    directly from the corpus's precomputed comparison matrix.
  - `bucket`: `"good"` (< 0.01), `"borderline"` (< 0.1), or `"large"`
    (>= 0.1) — derived from `mean_nrmse` for this specific pair. This is
    **not** the same as the `bucket` field in the source `index.json`,
    which is a per-job max over *all* engine pairs, not just
    copasi/tellurium.
  - `n_shared`: number of variables present in both engines' series for
    that model/job, counted from the (already-filtered) timecourse data
    itself.
  - Only present for `(biomodel_id, job)` pairs where both copasi and
    tellurium data made it into `corpus_timecourse.parquet`.

## Reading it

Use the `viva_biomodels.corpus_results` reader module (works from this repo
or as a vendored/installed dependency in another repo):

```python
from viva_biomodels.corpus_results import (
    load_corpus_timecourse,
    model_timecourse,
    load_corpus_metrics,
)

df = load_corpus_timecourse()               # full dataset
sub = model_timecourse(df, "BIOMD0000000001", engine="copasi")
metrics = load_corpus_metrics()
metrics["BIOMD0000000001"]["auto_ten_seconds"]["copasi__tellurium"]
```

`load_corpus_timecourse()` / `load_corpus_metrics()` default to the paths
committed here; pass an explicit `path=` to point elsewhere. Both raise a
clear `FileNotFoundError` if the dataset file is missing.
