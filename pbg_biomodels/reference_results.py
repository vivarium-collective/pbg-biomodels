"""Read BioSimulators SED-ML reference results into the composite leaf shape.

The BioSimulators test-suite stores one ``reports.h5`` per
``(biomodel, simulator, version)`` under a dataset directory laid out as::

    <root>/<BIOMD…>/<engine>/<version>/.../outputs/reports.h5

Inside each HDF5, SED-ML reports live under a ``<doc>.sedml`` group as 2-D
datasets shaped ``[n_dataset, n_timepoint]``. The row labels are carried in the
``sedmlDataSetLabels`` attribute (e.g. ``['Time', 'A', 'B', ...]``).

:func:`read_reference_leaf` converts the UTC report into the same flat
``map[observable -> timeseries]`` leaf the live runners emit (the ``Time`` row
becomes the reserved ``time`` key — see :mod:`pbg_biomodels.result_leaf`).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from pbg_biomodels.result_leaf import TIME_KEY

# Case-insensitive label that marks the sample-time row inside a SED-ML report.
_TIME_LABEL = "time"

# Member path of the report inside a BioSimulators ``results.zip``.
_ZIP_REPORT_MEMBER = "outputs/reports.h5"


def _decode(value: Any) -> str:
    """HDF5 attrs come back as ``str`` or ``bytes`` depending on the writer."""
    return value.decode() if isinstance(value, bytes) else str(value)


def read_reference_leaf(h5_path: str | Path) -> Dict[str, List[float]]:
    """Read the UTC SED-ML report from a ``reports.h5`` into a results leaf.

    Accepts either an extracted ``reports.h5`` or a BioSimulators
    ``results.zip`` (the as-shipped layout) — for a zip, the ``outputs/reports.h5``
    member is read in memory. Returns ``{time: [...], <observable>: [...], ...}``
    with the ``Time`` row remapped to the reserved ``time`` key; picks the first
    ``SedReport`` dataset that carries a time row.
    """
    import h5py

    if str(h5_path).lower().endswith(".zip"):
        import io
        import zipfile

        with zipfile.ZipFile(h5_path) as z:
            raw = z.read(_ZIP_REPORT_MEMBER)
        with h5py.File(io.BytesIO(raw), "r") as f:
            return _leaf_from_h5(f)

    with h5py.File(h5_path, "r") as f:
        return _leaf_from_h5(f)


def _leaf_from_h5(f) -> Dict[str, List[float]]:
    report = _find_utc_report(f)
    if report is None:
        return {}
    data = report[()]
    labels = [_decode(v) for v in report.attrs["sedmlDataSetLabels"]]
    leaf: Dict[str, List[float]] = {}
    for i, label in enumerate(labels):
        key = TIME_KEY if label.lower() == _TIME_LABEL else label
        leaf[key] = data[i].tolist()
    return leaf


def discover_reference_engines(root: str | Path, bid: str) -> List[str]:
    """Sorted engine names under ``<root>/<bid>/`` that have a ``reports.h5``."""
    model_dir = Path(root) / bid
    if not model_dir.is_dir():
        return []
    engines = [
        d.name
        for d in model_dir.iterdir()
        if d.is_dir() and not d.name.startswith(".") and resolve_engine_h5(root, bid, d.name)
    ]
    return sorted(engines)


def resolve_engine_h5(root: str | Path, bid: str, engine: str) -> Optional[Path]:
    """Locate one engine's ``reports.h5``, preferring the latest version dir.

    Prefers an extracted ``reports.h5`` (both on-disk variants ``<ver>/outputs/``
    and ``<ver>/results/outputs/``); falls back to the as-shipped
    ``<ver>/results.zip`` (which holds ``outputs/reports.h5``). Returns ``None``
    when the engine, file, and zip are all absent.
    """
    engine_dir = Path(root) / bid / engine
    if not engine_dir.is_dir():
        return None
    # Version dirs sorted descending so the newest wins.
    versions = sorted(
        (d for d in engine_dir.iterdir() if d.is_dir() and not d.name.startswith(".")),
        reverse=True,
    )
    for vdir in versions:
        hits = sorted(vdir.rglob("reports.h5"))
        if hits:
            return hits[0]
        zips = sorted(vdir.glob("results.zip"))
        if zips:
            return zips[0]
    return None


def _find_utc_report(group) -> Optional[Any]:
    """Depth-first search for the first SedReport dataset with a time row."""
    import h5py

    for key in group:
        item = group[key]
        if isinstance(item, h5py.Group):
            found = _find_utc_report(item)
            if found is not None:
                return found
            continue
        if _decode(item.attrs.get("_type", "")) != "SedReport":
            continue
        labels = [_decode(v).lower() for v in item.attrs.get("sedmlDataSetLabels", [])]
        if _TIME_LABEL in labels:
            return item
    return None
