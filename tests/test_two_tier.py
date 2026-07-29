"""Round-trip tests for the two-tier storage layer (index + parquet series).

Covers the subtle steady-state case: SS leaves carry no time vector, so they
must round-trip through parquet (NaN-time marker) and come back as steady-state
(is_utc False) rather than masquerading as a time course.
"""
import pytest

pytest.importorskip("pyarrow")

from viva_biomodels import result_leaf
from viva_biomodels.two_tier import write_model
from viva_biomodels.lazy_viewer import _parquet_leaves_aligned


def _model_results():
    return {
        "auto_ten_seconds": {  # UTC: time + observables
            "copasi": {"time": [0.0, 1.0, 2.0], "A": [10.0, 5.0, 2.5], "B": [0.0, 5.0, 7.5]},
            "tellurium": {"time": [0.0, 1.0, 2.0], "A": [10.0, 5.1, 2.4], "B": [0.0, 4.9, 7.6]},
        },
        "auto_steady_state": {  # steady-state: length-1 values, NO time
            "amici": {"A": [2.5], "B": [7.5]},
            "pysces": {"A": [2.51], "B": [7.49]},
        },
    }


def test_two_tier_roundtrip_utc_and_steady_state(tmp_path):
    bid = "BIOMD0000000001"
    entry = write_model(bid, _model_results(), {}, tmp_path, max_points=200)

    # index entry records both jobs with the right kind.
    kinds = {job: j["kind"] for job, j in entry["jobs"].items()}
    assert kinds["auto_ten_seconds"] == "utc"
    assert kinds["auto_steady_state"] == "steady_state"

    leaves = _parquet_leaves_aligned(tmp_path, bid)

    # UTC leaf comes back WITH a time vector.
    utc = leaves["auto_ten_seconds"]["copasi"]
    assert result_leaf.is_utc(utc) is True
    assert utc["time"] == pytest.approx([0.0, 1.0, 2.0])
    assert utc["A"] == pytest.approx([10.0, 5.0, 2.5])

    # Steady-state leaf comes back WITHOUT a time key (is_utc False), values intact.
    ss = leaves["auto_steady_state"]["amici"]
    assert result_leaf.is_utc(ss) is False
    assert "time" not in ss
    assert ss["A"] == pytest.approx([2.5])
    assert ss["B"] == pytest.approx([7.5])
