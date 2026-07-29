"""Export a batch-comparison run to a single, self-describing **zarr** artifact.

The zarr is laid out in the hierarchy a downstream consumer asked for —
``biomodel_id / simulator / sedml_job_id`` — with each leaf an
xarray-loadable group (a ``time`` or ``scan`` coordinate plus one array per
observable). BioSimulators reference engines are folded in as ordinary
simulator-level groups named ``reference_<engine>`` (the ``:`` in
``reference:<engine>`` is sanitized so the store is portable to Windows).

Two producers share :func:`write_zarr`:

* :class:`viva_biomodels.steps.export_zarr.ZarrExportStep` — a Step wired at the
  end of the ``batch-compare-biomodels`` composite; it consumes the in-memory
  ``results``/``comparisons``/``diagnostics`` stores and writes the zarr,
  emitting ``zarr_path``.
* :func:`zarr_from_two_tier` — an offline converter that reconstructs the same
  structure from an existing two-tier output dir (``index.json`` +
  ``series/<bid>.parquet``) so a completed large run can be exported without
  re-running. Note the two-tier series are downsampled (float32, ~200 points).

Layout::

    root/                       .attrs: {engines, biomodels, generated_utc, source, schema}
      BIOMD0000000012/          .attrs: {comparisons: {job: {matrix, bucket, ...}}, runs: {...}}
        copasi/
          auto_ten_seconds/     xr.Dataset  (dims: time; vars: A, B, ...)  .attrs: {kind, simulator, ...}
        reference_vcell/
          auto_ten_seconds/     xr.Dataset  ...
      ...

Load with, e.g.::

    import xarray as xr
    ds = xr.open_zarr("compare_all_1054.zarr/BIOMD0000000012/copasi/auto_ten_seconds")
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from viva_biomodels import result_leaf


# ---------------------------------------------------------------------------
# Name sanitation — zarr node names become directory names in a LocalStore, so
# keep them portable (no ':' / '/' / '\'). Originals are preserved in attrs.
# ---------------------------------------------------------------------------
def _safe(name: str) -> str:
    return str(name).replace(":", "_").replace("/", "_").replace("\\", "_")


def _jsonable(obj: Any) -> Any:
    """Coerce numpy scalars / non-finite floats to plain JSON-safe values."""
    import math

    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if hasattr(obj, "item"):  # numpy scalar
        try:
            return _jsonable(obj.item())
        except Exception:
            return str(obj)
    return obj


def _leaf_dataset(leaf: Dict[str, Any], attrs: Dict[str, Any]):
    """Build an xarray Dataset for one (biomodel, simulator, sedml_job) leaf.

    To keep the full-corpus store to a manageable file count, each leaf is
    packed into a **single** ``value`` array rather than one array per
    observable:

    * UTC / scan leaves: ``value`` has dims ``(time|scan, observable)`` with an
      ``observable`` string coordinate (names verbatim) and the ordered axis
      coordinate.
    * steady-state leaves: ``value`` has dims ``(observable,)``.

    Access is ``ds["value"].sel(observable="A")``. ``attrs`` land in the group's
    ``.zattrs``.
    """
    import numpy as np
    import xarray as xr

    axis_name, axis_vals = result_leaf.axis_of(leaf)
    obs = result_leaf.observables_of(leaf)

    if axis_name:  # utc (time) or repeated_task (scan)
        axis = np.asarray([float(x) for x in axis_vals], dtype="float32")
        names = [v for v in obs if isinstance(obs[v], list) and len(obs[v]) > 0]
        # Align every series + the coord to the shortest present length.
        m = min([len(axis)] + [len(obs[v]) for v in names]) if names else len(axis)
        data = np.full((m, len(names)), np.nan, dtype="float32")
        for j, v in enumerate(names):
            col = np.asarray([float(x) for x in obs[v][:m]], dtype="float32")
            data[:, j] = col
        ds = xr.Dataset(
            {"value": ((axis_name, "observable"), data)},
            coords={axis_name: axis[:m],
                    "observable": np.asarray(names, dtype=object)},
        )
    else:  # steady-state — one scalar per observable
        vals = result_leaf.steady_state_scalars(leaf)
        names = list(vals)
        data = np.asarray([float(vals[v]) for v in names], dtype="float32")
        ds = xr.Dataset(
            {"value": (("observable",), data)},
            coords={"observable": np.asarray(names, dtype=object)},
        )

    ds.attrs.update(_jsonable(attrs))
    return ds


def write_zarr(
    path: str | Path,
    results: Dict[str, Dict[str, Dict[str, Any]]],
    comparisons: Optional[Dict[str, Any]] = None,
    diagnostics: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> str:
    """Write the hierarchical zarr artifact and return its absolute path.

    Args:
        path: output ``.zarr`` directory (created / overwritten).
        results: the batch store keyed ``biomodel > sedml_job > simulator > leaf``
            (the internal order); this function re-nests it to
            ``biomodel > simulator > sedml_job`` in the zarr.
        comparisons: ``{biomodel: {sedml_job: <compare rollup>}}`` — stored as
            per-biomodel group attrs.
        diagnostics: run diagnostics; its ``runs``/``provenance`` are stored as
            per-biomodel group attrs and root attrs.
        meta: extra root-level attributes (merged with derived defaults).
    """
    import zarr

    path = Path(path)
    comparisons = comparisons or {}
    diagnostics = diagnostics or {}
    runs = (diagnostics.get("runs") or {}) if isinstance(diagnostics, dict) else {}

    engines: set = set()
    n_leaves = 0
    first = True

    for bid, job_map in results.items():
        for job, sim_map in (job_map or {}).items():
            for sim, leaf in (sim_map or {}).items():
                if not leaf:
                    continue  # failed/empty run — no group
                engines.add(sim)
                run_rec = ((runs.get(bid) or {}).get(job) or {}).get(sim) or {}
                attrs = {
                    "biomodel": bid,
                    "simulator": sim,
                    "is_reference": str(sim).startswith("reference:"),
                    "sedml_job": job,
                    "kind": result_leaf.kind_of(leaf),
                    "status": run_rec.get("status"),
                    "runtime_s": run_rec.get("runtime_s"),
                    "n_points": run_rec.get("n_points"),
                }
                ds = _leaf_dataset(leaf, attrs)
                group = f"{_safe(bid)}/{_safe(sim)}/{_safe(job)}"
                ds.to_zarr(
                    path, group=group,
                    mode="w" if first else "a",
                    zarr_format=3, consolidated=False,
                )
                first = False
                n_leaves += 1

    if first:
        raise ValueError("write_zarr: no non-empty result leaves to export.")

    # Group- and root-level attributes (written after arrays exist).
    root = zarr.open_group(str(path), mode="a")
    root_attrs = {
        "schema": "biomodel_id / simulator / sedml_job_id -> Dataset(observable[, time|scan])",
        "engines": sorted(engines),
        "biomodels": sorted(results.keys()),
        "n_biomodels": len(results),
        "n_leaves": n_leaves,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    root_attrs.update(_jsonable(meta or {}))
    for k, v in root_attrs.items():
        root.attrs[k] = v

    for bid in results:
        safe_bid = _safe(bid)
        if safe_bid not in root:
            continue
        g = root[safe_bid]
        bcmp = _jsonable(comparisons.get(bid) or {})
        if bcmp:
            g.attrs["comparisons"] = bcmp
        bruns = _jsonable(runs.get(bid) or {})
        if bruns:
            g.attrs["runs"] = bruns
        g.attrs["biomodel"] = bid

    # Consolidate so `xr.open_zarr(..., consolidated=True)` opens fast without a
    # fallback warning. (Consolidated metadata is an xarray/zarr-python
    # convention rather than part of the zarr v3 spec; best-effort.)
    try:
        zarr.consolidate_metadata(str(path))
    except Exception:
        pass
    return str(path.resolve())


# ---------------------------------------------------------------------------
# Offline converter: existing two-tier output dir -> zarr
# ---------------------------------------------------------------------------
def _reconstruct_results_from_parquet(series_dir: Path, kinds: Dict[str, Dict[str, str]]):
    """Rebuild ``{bid: {job: {engine: leaf}}}`` from ``series/<bid>.parquet``.

    ``kinds[bid][job]`` gives the job kind (utc / steady_state / repeated_task)
    from ``index.json`` — needed to label the stored axis (the two-tier writer
    puts both time and scan axes in the generic ``time`` column, and marks
    steady-state rows with NaN times).
    """
    import math

    import pyarrow.parquet as pq

    results: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for pq_file in sorted(series_dir.glob("*.parquet")):
        bid = pq_file.stem
        df = pq.read_table(pq_file).to_pandas()
        if df.empty:
            continue
        results[bid] = {}
        job_kinds = kinds.get(bid) or {}
        for (job, engine), g in df.groupby(["job", "engine"], sort=False, observed=True):
            if g.empty:
                continue
            kind = job_kinds.get(job) or ("steady_state"
                                          if g["time"].isna().all() else "utc")
            leaf: Dict[str, Any] = {}
            if kind == "steady_state":
                for var, sub in g.groupby("variable", sort=False, observed=True):
                    vals = [float(x) for x in sub["value"].tolist()]
                    if vals:
                        leaf[str(var)] = [vals[0]]
            else:
                axis_key = "scan" if kind == "repeated_task" else "time"
                first_var = g["variable"].iloc[0]
                axis = [float(x) for x in g[g["variable"] == first_var]["time"].tolist()]
                # Drop NaN padding that steady-state marking may have introduced.
                axis = [x for x in axis if not math.isnan(x)] or axis
                leaf[axis_key] = axis
                for var, sub in g.groupby("variable", sort=False, observed=True):
                    ys = [float(x) for x in sub["value"].tolist()]
                    if ys:
                        leaf[str(var)] = ys
            results[bid].setdefault(job, {})[str(engine)] = leaf
    return results


def zarr_from_two_tier(out_dir: str | Path, zarr_path: str | Path) -> str:
    """Convert an existing two-tier batch output dir to the zarr artifact.

    Reads ``<out_dir>/index.json`` (comparisons, job kinds, run provenance) and
    ``<out_dir>/series/<bid>.parquet`` (the downsampled time series, live +
    reference engines) and writes ``zarr_path``.
    """
    out_dir = Path(out_dir)
    index = json.loads((out_dir / "index.json").read_text(encoding="utf-8"))
    models = index.get("models") or {}

    # job kinds + per-biomodel comparisons + runs from the index.
    kinds: Dict[str, Dict[str, str]] = {}
    comparisons: Dict[str, Any] = {}
    runs: Dict[str, Any] = {}
    for bid, rec in models.items():
        jobs = rec.get("jobs") or {}
        kinds[bid] = {job: (j.get("kind") or "utc") for job, j in jobs.items()}
        comparisons[bid] = {
            job: {
                "engines": j.get("engines"),
                "matrix": j.get("matrix"),
                "max_nrmse": j.get("max_nrmse"),
                "bucket": j.get("bucket"),
                "matrix_closeness": j.get("matrix_closeness"),
                "max_score": j.get("max_score"),
                "closeness_bucket": j.get("closeness_bucket"),
                "n_ok": j.get("n_ok"),
                "n_failed": j.get("n_failed"),
                "kind": j.get("kind"),
            }
            for job, j in jobs.items()
        }
        if rec.get("runs"):
            runs[bid] = rec["runs"]

    results = _reconstruct_results_from_parquet(out_dir / "series", kinds)

    meta = {
        "source": f"two-tier converter from {out_dir.name}",
        "resolution_note": "series are downsampled (float32, ~200 points) — the "
                           "surviving form of this run; not full ODE-solver resolution",
        "corpus_meta": _jsonable(index.get("meta") or {}),
    }
    return write_zarr(zarr_path, results, comparisons=comparisons,
                      diagnostics={"runs": runs}, meta=meta)


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Export a batch-comparison run to a single zarr artifact "
                    "(biomodel/simulator/sedml_job hierarchy).")
    ap.add_argument("--from-two-tier", required=True,
                    help="two-tier output dir (contains index.json + series/).")
    ap.add_argument("--out", required=True, help="output .zarr path.")
    ap.add_argument("--zip", action="store_true",
                    help="also write <out>.zip for easy sharing.")
    a = ap.parse_args(argv)

    path = zarr_from_two_tier(a.from_two_tier, a.out)
    print(f"Wrote zarr: {path}")
    if a.zip:
        import shutil

        base = str(Path(a.out))
        zip_path = shutil.make_archive(base, "zip", root_dir=path)
        print(f"Wrote zip:  {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
