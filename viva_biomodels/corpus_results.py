"""Reader for the committed corpus comparison dataset (Task Z0).

The dataset (``datasets/corpus_comparison/``) is a trimmed, downsampled
COPASI + Tellurium time-course corpus derived from the full compare-all
sweep (``out/compare_all_1054``, not committed). It's small and
git-friendly on purpose so other repos can vendor or read it directly
without touching the multi-hundred-MB raw run output.

    from viva_biomodels.corpus_results import (
        load_corpus_timecourse,
        model_timecourse,
        load_corpus_metrics,
    )

    df = load_corpus_timecourse()
    sub = model_timecourse(df, "BIOMD0000000001", engine="copasi")
    metrics = load_corpus_metrics()
    metrics["BIOMD0000000001"]["auto_ten_seconds"]["copasi__tellurium"]
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

# Package root is viva_biomodels/; the dataset lives at
# <repo_root>/datasets/corpus_comparison/ (a sibling of the package dir).
_PACKAGE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PACKAGE_DIR.parent
_DATASET_DIR = _REPO_ROOT / "datasets" / "corpus_comparison"

DEFAULT_TIMECOURSE_PATH = _DATASET_DIR / "corpus_timecourse.parquet"
DEFAULT_METRICS_PATH = _DATASET_DIR / "corpus_metrics.json"


def _resolve_path(path: str | Path | None, default: Path) -> Path:
    return Path(path) if path is not None else default


def load_corpus_timecourse(path: str | Path | None = None) -> pd.DataFrame:
    """Load the committed corpus time-course dataset.

    Parameters
    ----------
    path:
        Optional override; defaults to the committed
        ``datasets/corpus_comparison/corpus_timecourse.parquet`` resolved
        relative to this package's location.

    Returns
    -------
    DataFrame with columns ``[biomodel_id, job, engine, variable, time,
    value]``, engines limited to ``copasi``/``tellurium``, downsampled to
    at most ~100 points per (biomodel_id, job, engine, variable) series.
    """
    resolved = _resolve_path(path, DEFAULT_TIMECOURSE_PATH)
    if not resolved.exists():
        raise FileNotFoundError(
            f"Corpus timecourse dataset not found at {resolved}. "
            "Run scripts/build_corpus_dataset.py to (re)generate it, or "
            "pass an explicit path= to load_corpus_timecourse()."
        )
    return pd.read_parquet(resolved)


def model_timecourse(
    biomodel_id_or_df,
    biomodel_id: str | None = None,
    *,
    engine: str | None = None,
    job: str | None = None,
) -> pd.DataFrame:
    """Filter a corpus time-course dataframe down to one biomodel.

    Accepts either:
        model_timecourse(df, "BIOMD0000000001", engine="copasi")
    or, for convenience, loads the default dataset itself when given only
    an id:
        model_timecourse("BIOMD0000000001")

    Parameters
    ----------
    biomodel_id_or_df:
        Either a DataFrame (as returned by ``load_corpus_timecourse``) or
        a biomodel id string.
    biomodel_id:
        The biomodel id to filter to, when the first argument is a
        DataFrame.
    engine, job:
        Optional further filters (e.g. ``engine="copasi"``,
        ``job="auto_ten_seconds"``).
    """
    if isinstance(biomodel_id_or_df, pd.DataFrame):
        df = biomodel_id_or_df
        target_id = biomodel_id
    else:
        df = load_corpus_timecourse()
        target_id = biomodel_id_or_df

    if target_id is None:
        raise ValueError("model_timecourse requires a biomodel_id")

    mask = df["biomodel_id"].astype(str) == str(target_id)
    if engine is not None:
        mask &= df["engine"].astype(str) == str(engine)
    if job is not None:
        mask &= df["job"].astype(str) == str(job)
    return df[mask]


def load_corpus_metrics(path: str | Path | None = None) -> dict:
    """Load the committed copasi<->tellurium pairwise metrics summary.

    Returns a dict shaped:
        {biomodel_id: {job: {"copasi__tellurium": {mean_nrmse, bucket, n_shared}}}}
    """
    import json

    resolved = _resolve_path(path, DEFAULT_METRICS_PATH)
    if not resolved.exists():
        raise FileNotFoundError(
            f"Corpus metrics file not found at {resolved}. "
            "Run scripts/build_corpus_dataset.py to (re)generate it, or "
            "pass an explicit path= to load_corpus_metrics()."
        )
    return json.loads(resolved.read_text(encoding="utf-8"))
