"""The overlay figure is capped so many-observable models stay responsive."""
from pbg_biomodels.lazy_viewer import _cap_leaves


def _leaf(nobs):
    leaf = {"time": [0.0, 1.0]}
    for i in range(nobs):
        leaf[f"s{i}"] = [float(i), float(i)]
    return leaf


def test_cap_trims_to_n_observables():
    leaves = {"copasi": _leaf(100), "tellurium": _leaf(100)}
    capped, shown, total = _cap_leaves(leaves, 24)
    assert shown == 24 and total == 100
    # each capped leaf keeps the axis + only 24 observables
    obs = [k for k in capped["copasi"] if k != "time"]
    assert len(obs) == 24
    assert "time" in capped["copasi"]


def test_cap_noop_when_under_limit():
    leaves = {"copasi": _leaf(5)}
    capped, shown, total = _cap_leaves(leaves, 24)
    assert (shown, total) == (5, 5)
    assert capped is leaves
