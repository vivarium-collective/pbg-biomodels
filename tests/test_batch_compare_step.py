"""`BatchCompareStep` reads the full nested results store
(map[bid, map[sedml_job, map[sim, results]]], simulator innermost) and produces
comparisons[bid][sedml_job] using compare_n_engines (UTC) or
compare_n_engines_steady_state (SS). Each leaf is a flat
`map[observable -> timeseries]`; UTC carries the reserved `time` key, steady
state omits it and stores length-1 lists.
"""
from typing import Any, Dict
import warnings

import pytest
from process_bigraph import allocate_core

from viva_biomodels.steps.simulator_comparison import BatchCompareStep


def _utc(time, observables):
    """A UTC results leaf: flat map[observable -> timeseries] + reserved time."""
    return {"time": list(time), **observables}


def _ss(observables):
    """A steady-state results leaf: each observable as a length-1 list, no time."""
    return {k: [v] for k, v in observables.items()}


def test_utc_pairs_use_nrmse_per_species():
    out = BatchCompareStep(core=allocate_core()).update({
        "results": {
            "BIOMD0000000001": {
                "sim1": {
                    "copasi":    _utc([0.0, 1.0], {"A": [1.0, 0.5], "B": [0.0, 0.5]}),
                    "tellurium": _utc([0.0, 1.0], {"A": [1.0, 0.5], "B": [0.0, 0.5]}),
                },
            },
        }
    })
    cmp = out["comparisons"]["BIOMD0000000001"]["sim1"]
    assert cmp["engines"] == ["copasi", "tellurium"]
    assert cmp["bucket"] == "good"


def test_ss_pairs_use_steady_state_metric():
    out = BatchCompareStep(core=allocate_core()).update({
        "results": {
            "BIOMD0000000001": {
                "sim_ss": {
                    "copasi":    _ss({"A": 1.0,  "B": 2.0}),
                    "tellurium": _ss({"A": 1.0,  "B": 2.0}),
                    "simbio":    _ss({"A": 1.05, "B": 2.0}),
                },
            },
        }
    })
    cmp = out["comparisons"]["BIOMD0000000001"]["sim_ss"]
    assert set(cmp["engines"]) == {"copasi", "tellurium", "simbio"}
    # copasi vs tellurium is identical; copasi vs simbio has a 5% offset on A.
    assert cmp["bucket"] in {"good", "borderline"}


def test_cross_kind_under_one_sedml_doc_is_skipped_with_warning():
    """A SED-ML job that ends up with both UTC and SS results across
    simulators is a pathological case — record a warning, emit empty."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = BatchCompareStep(core=allocate_core()).update({
            "results": {
                "BIOMD0000000001": {
                    "sim1": {
                        "copasi":    _utc([0.0], {"A": [1.0]}),
                        "tellurium": _ss({"A": 1.0}),
                    },
                },
            }
        })
    cmp = out["comparisons"]["BIOMD0000000001"]["sim1"]
    assert cmp["engines"] == []
    assert cmp["bucket"] == "none"
    assert any("mixed kinds" in str(w.message) for w in caught)


def test_simulator_with_no_result_for_sedml_doc_is_dropped():
    """A simulator whose run failed (empty leaf) for a sedml job is excluded
    from that job's comparison."""
    out = BatchCompareStep(core=allocate_core()).update({
        "results": {
            "BIOMD0000000001": {
                "sim1": {
                    "copasi":    _utc([0.0], {"A": [1.0]}),
                    "tellurium": {},  # simulator produced nothing (failed)
                },
            },
        }
    })
    cmp = out["comparisons"]["BIOMD0000000001"]["sim1"]
    assert cmp["engines"] == ["copasi"]  # only the one engine with data
