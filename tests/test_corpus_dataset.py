"""Tests for the corpus comparison dataset builder + reader (Task Z0).

Builds a tiny synthetic ``series/`` directory (mimicking
``out/compare_all_1054``) in a tmp dir, runs the builder's core function
against it, and checks the resulting parquet + metrics json. Also exercises
the reader module (``viva_biomodels.corpus_results``) against the same
synthetic output.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILDER_PATH = REPO_ROOT / "scripts" / "build_corpus_dataset.py"


def _load_builder_module():
    spec = importlib.util.spec_from_file_location("build_corpus_dataset", BUILDER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


builder = _load_builder_module()


def _load_corpus_results_module():
    # Load corpus_results.py directly from its file rather than via
    # `from viva_biomodels import corpus_results`: the canonical checkout's
    # installed venv currently has an unrelated import-chain mismatch in
    # viva_biomodels/__init__.py (composites -> ... -> viva_superpowers,
    # a package not present in this venv's pbg-superpowers 0.15.0 pin).
    # That's an environment issue orthogonal to this dataset/reader module,
    # so we bypass the package __init__ the same way the builder script
    # (also not part of the viva_biomodels package) is loaded above.
    module_path = REPO_ROOT / "viva_biomodels" / "corpus_results.py"
    spec = importlib.util.spec_from_file_location("corpus_results", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


corpus_results = _load_corpus_results_module()


def _make_series_df(job: str, engine: str, variables: dict[str, int]) -> pd.DataFrame:
    """Build a tidy series frame for one engine with >100 points/variable."""
    frames = []
    for var, n_points in variables.items():
        time = np.linspace(0.0, 10.0, n_points, dtype=np.float32)
        value = np.sin(time) + hash((engine, var)) % 7
        frames.append(
            pd.DataFrame(
                {
                    "job": job,
                    "engine": engine,
                    "variable": var,
                    "time": time,
                    "value": value.astype(np.float32),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


@pytest.fixture
def synthetic_source(tmp_path: Path) -> Path:
    source = tmp_path / "compare_all_synth"
    series_dir = source / "series"
    series_dir.mkdir(parents=True)

    # BIOMD_A: copasi + tellurium + amici, 2 shared variables, 250 points each
    # (well above the 100-point downsample cap).
    df_a = pd.concat(
        [
            _make_series_df("auto_ten_seconds", "copasi", {"A": 250, "B": 250}),
            _make_series_df("auto_ten_seconds", "tellurium", {"A": 250, "B": 250}),
            _make_series_df("auto_ten_seconds", "amici", {"A": 250, "B": 250}),
        ],
        ignore_index=True,
    )
    df_a.to_parquet(series_dir / "BIOMD_A.parquet")

    # BIOMD_B: only copasi + amici (no tellurium) -> should still contribute
    # copasi rows to the timecourse, but get NO copasi__tellurium metrics
    # entry (pair not present).
    df_b = pd.concat(
        [
            _make_series_df("auto_steady_state", "copasi", {"C": 150}),
            _make_series_df("auto_steady_state", "amici", {"C": 150}),
        ],
        ignore_index=True,
    )
    df_b.to_parquet(series_dir / "BIOMD_B.parquet")

    # BIOMD_C: only amici -> should be skipped entirely (neither engine present).
    df_c = _make_series_df("auto_ten_seconds", "amici", {"D": 120})
    df_c.to_parquet(series_dir / "BIOMD_C.parquet")

    index = {
        "models": {
            "BIOMD_A": {
                "jobs": {
                    "auto_ten_seconds": {
                        "matrix": {
                            "copasi": {"tellurium": 0.0042, "amici": 0.9},
                            "tellurium": {"copasi": 0.0042, "amici": 0.9},
                            "amici": {"copasi": 0.9, "tellurium": 0.9},
                        },
                    }
                }
            },
            "BIOMD_B": {
                "jobs": {
                    "auto_steady_state": {
                        "matrix": {
                            "copasi": {"amici": 0.5},
                            "amici": {"copasi": 0.5},
                        },
                    }
                }
            },
            "BIOMD_C": {
                "jobs": {
                    "auto_ten_seconds": {
                        "matrix": {"amici": {}},
                    }
                }
            },
        },
        "meta": {"n_models": 3},
    }
    (source / "index.json").write_text(json.dumps(index), encoding="utf-8")
    return source


def test_build_dataset_filters_engines_and_downsamples(synthetic_source, tmp_path):
    out_dir = tmp_path / "out_dataset"
    stats = builder.build_dataset(synthetic_source, out_dir, max_points=100)

    parquet_path = out_dir / "corpus_timecourse.parquet"
    assert parquet_path.exists()

    df = pd.read_parquet(parquet_path)
    assert list(df.columns) == ["biomodel_id", "job", "engine", "variable", "time", "value"]

    # Only copasi/tellurium survive; amici is filtered out entirely.
    assert set(df["engine"].astype(str).unique()) == {"copasi", "tellurium"}
    # BIOMD_C had neither engine -> fully absent.
    assert "BIOMD_C" not in set(df["biomodel_id"].astype(str).unique())
    # BIOMD_B's copasi rows still show up even without a tellurium partner.
    assert "BIOMD_B" in set(df["biomodel_id"].astype(str).unique())

    # Downsample cap respected per (biomodel_id, job, engine, variable) group.
    counts = df.groupby(["biomodel_id", "job", "engine", "variable"], observed=True).size()
    assert (counts <= 100).all()
    assert counts.max() > 1  # sanity: didn't collapse to single points

    assert df["time"].dtype == np.float32
    assert df["value"].dtype == np.float32

    assert stats["n_models_with_data"] == 2  # BIOMD_A, BIOMD_B
    assert stats["n_rows"] == len(df)

    # Metrics file.
    metrics_path = out_dir / "corpus_metrics.json"
    assert metrics_path.exists()
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))

    entry = metrics["BIOMD_A"]["auto_ten_seconds"]["copasi__tellurium"]
    assert entry["mean_nrmse"] == pytest.approx(0.0042)
    assert entry["bucket"] == "good"
    assert entry["n_shared"] == 2  # variables A and B present in both engines

    # BIOMD_B has no tellurium at all -> no copasi__tellurium pair recorded.
    assert "auto_steady_state" not in metrics.get("BIOMD_B", {}) or (
        "copasi__tellurium" not in metrics["BIOMD_B"].get("auto_steady_state", {})
    )
    # BIOMD_C skipped outright.
    assert "BIOMD_C" not in metrics


def test_derive_bucket_thresholds():
    assert builder.derive_bucket(0.0) == "good"
    assert builder.derive_bucket(0.005) == "good"
    assert builder.derive_bucket(0.05) == "borderline"
    assert builder.derive_bucket(0.5) == "large"
    assert builder.derive_bucket(None) == "none"


def test_reader_load_and_filter(synthetic_source, tmp_path):
    out_dir = tmp_path / "out_dataset2"
    builder.build_dataset(synthetic_source, out_dir, max_points=100)

    df = corpus_results.load_corpus_timecourse(out_dir / "corpus_timecourse.parquet")
    assert set(df["engine"].astype(str).unique()) == {"copasi", "tellurium"}

    sub = corpus_results.model_timecourse(df, "BIOMD_A", engine="copasi", job="auto_ten_seconds")
    assert (sub["biomodel_id"] == "BIOMD_A").all()
    assert (sub["engine"] == "copasi").all()
    assert (sub["job"] == "auto_ten_seconds").all()
    assert len(sub) > 0

    metrics = corpus_results.load_corpus_metrics(out_dir / "corpus_metrics.json")
    assert metrics["BIOMD_A"]["auto_ten_seconds"]["copasi__tellurium"]["bucket"] == "good"


def test_model_timecourse_accepts_biomodel_id_or_dataframe(synthetic_source, tmp_path):
    out_dir = tmp_path / "out_dataset3"
    builder.build_dataset(synthetic_source, out_dir, max_points=100)
    df = corpus_results.load_corpus_timecourse(out_dir / "corpus_timecourse.parquet")

    all_a = corpus_results.model_timecourse(df, "BIOMD_A")
    assert set(all_a["engine"].astype(str).unique()) == {"copasi", "tellurium"}


def test_load_corpus_timecourse_missing_file_raises_clear_error(tmp_path):
    missing = tmp_path / "does_not_exist.parquet"
    with pytest.raises(FileNotFoundError, match="does_not_exist.parquet"):
        corpus_results.load_corpus_timecourse(missing)


def test_load_corpus_metrics_missing_file_raises_clear_error(tmp_path):
    missing = tmp_path / "nope.json"
    with pytest.raises(FileNotFoundError, match="nope.json"):
        corpus_results.load_corpus_metrics(missing)


def test_downsample_group_respects_cap():
    time = np.linspace(0, 100, 500, dtype=np.float32)
    df = pd.DataFrame({"time": time, "value": time * 2})
    result = builder.downsample_group(df, max_points=60)
    assert len(result) <= 60
    # First and last timepoints preserved (even stride keeps endpoints).
    assert result["time"].iloc[0] == pytest.approx(time[0])
    assert result["time"].iloc[-1] == pytest.approx(time[-1])


def test_downsample_group_noop_when_under_cap():
    time = np.linspace(0, 10, 50, dtype=np.float32)
    df = pd.DataFrame({"time": time, "value": time})
    result = builder.downsample_group(df, max_points=100)
    assert len(result) == 50
