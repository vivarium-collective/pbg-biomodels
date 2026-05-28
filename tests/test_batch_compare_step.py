"""`BatchCompareStep` reads the full nested results store
(map[sim, map[bid, map[sedml_doc, simulation_result]]]) and produces
comparisons[bid][sedml_doc] using compare_n_engines (UTC) or
compare_n_engines_steady_state (SS).
"""
from typing import Any, Dict
import warnings

import pytest
from process_bigraph import allocate_core

from pbg_biomodels.steps.simulator_comparison import BatchCompareStep


def _utc(time, observables):
    return {"kind": "utc", "time": time, "observables": observables}


def _ss(observables):
    return {"kind": "steady_state", "time": None, "observables": observables}


def test_utc_pairs_use_nrmse_per_species():
    out = BatchCompareStep(core=allocate_core()).update({
        "results": {
            "copasi": {
                "BIOMD0000000001": {"sim1": _utc([0.0, 1.0],
                                                  {"A": [1.0, 0.5], "B": [0.0, 0.5]})},
            },
            "tellurium": {
                "BIOMD0000000001": {"sim1": _utc([0.0, 1.0],
                                                  {"A": [1.0, 0.5], "B": [0.0, 0.5]})},
            },
        }
    })
    cmp = out["comparisons"]["BIOMD0000000001"]["sim1"]
    assert cmp["engines"] == ["copasi", "tellurium"]
    assert cmp["bucket"] == "good"


def test_ss_pairs_use_steady_state_metric():
    out = BatchCompareStep(core=allocate_core()).update({
        "results": {
            "copasi":    {"BIOMD0000000001": {"sim_ss": _ss({"A": 1.0, "B": 2.0})}},
            "tellurium": {"BIOMD0000000001": {"sim_ss": _ss({"A": 1.0, "B": 2.0})}},
            "simbio":    {"BIOMD0000000001": {"sim_ss": _ss({"A": 1.05, "B": 2.0})}},
        }
    })
    cmp = out["comparisons"]["BIOMD0000000001"]["sim_ss"]
    assert set(cmp["engines"]) == {"copasi", "tellurium", "simbio"}
    # copasi vs tellurium is identical; copasi vs simbio has a 5% offset on A.
    assert cmp["bucket"] in {"good", "borderline"}


def test_cross_kind_under_one_sedml_doc_is_skipped_with_warning():
    """A SED-ML doc that ends up with both UTC and SS results across
    simulators is a pathological case — record a warning, emit empty."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = BatchCompareStep(core=allocate_core()).update({
            "results": {
                "copasi":    {"BIOMD0000000001": {"sim1": _utc([0.0], {"A": [1.0]})}},
                "tellurium": {"BIOMD0000000001": {"sim1": _ss({"A": 1.0})}},
            }
        })
    cmp = out["comparisons"]["BIOMD0000000001"]["sim1"]
    assert cmp["engines"] == []
    assert cmp["bucket"] == "none"
    assert any("mixed kinds" in str(w.message) for w in caught)


def test_simulator_with_no_result_for_sedml_doc_is_dropped():
    """A simulator that doesn't have an entry for a sedml doc is excluded
    from that doc's comparison."""
    out = BatchCompareStep(core=allocate_core()).update({
        "results": {
            "copasi":    {"BIOMD0000000001": {"sim1": _utc([0.0], {"A": [1.0]})}},
            "tellurium": {"BIOMD0000000001": {}},  # simulator ran nothing for this biomodel
        }
    })
    cmp = out["comparisons"]["BIOMD0000000001"]["sim1"]
    assert cmp["engines"] == ["copasi"]  # only the one engine with data
