"""All-pairs steady-state comparison: |a-b| / max(|a|,|b|, eps) per observable."""
from viva_biomodels.comparison import compare_n_engines_steady_state


def test_two_engines_identical_are_in_good_bucket():
    out = compare_n_engines_steady_state({
        "copasi":    {"A": 1.0, "B": 2.0},
        "tellurium": {"A": 1.0, "B": 2.0},
    })
    assert out["engines"] == ["copasi", "tellurium"]
    assert out["max_nrmse"] == 0.0
    assert out["bucket"] == "good"


def test_disjoint_observables_are_not_compared():
    out = compare_n_engines_steady_state({
        "copasi":    {"A": 1.0},
        "tellurium": {"B": 1.0},
    })
    # No shared observables → no nrmse value for that pair.
    pair = out["pairs"]["copasi__tellurium"]
    assert pair["n_shared"] == 0
    assert pair["mean_nrmse"] is None


def test_three_engines_picks_worst_pair():
    out = compare_n_engines_steady_state({
        "copasi":    {"A": 1.0},
        "tellurium": {"A": 1.1},   # 10% off copasi
        "simbio":    {"A": 2.0},   # 50% off copasi (worst pair)
    })
    assert out["max_nrmse"] > 0.4
    assert set(out["worst_pair"]) == {"copasi", "simbio"}
    assert out["bucket"] in {"borderline", "large"}
