"""`SimulatorRunnerStep` iterates a `models` map and dispatches each
SED-ML job to its simulator's UTC or SteadyState adapter, writing into
a nested `results` map shaped `map[bid, map[sedml_doc, simulation_result]]`.
"""
from typing import Any, Dict

import pytest
from process_bigraph import allocate_core


def _utc_payload():
    return {
        "result": {
            "time":    [0.0, 0.5, 1.0],
            "columns": ["A", "B"],
            "values":  [[1.0, 0.0], [0.6, 0.4], [0.3, 0.7]],
        }
    }


def _ss_payload():
    return {
        "result": {
            "kind":        "steady_state",
            "time":        None,
            "observables": {"A": 0.25, "B": 0.75},
        }
    }


class _StubUTC:
    def __init__(self, config=None, core=None):
        pass

    def update(self, _state):
        return _utc_payload()


class _StubSS:
    def __init__(self, config=None, core=None):
        pass

    def update(self, _state):
        return _ss_payload()


class _RaisingUTC:
    def __init__(self, config=None, core=None):
        pass

    def update(self, _state):
        raise RuntimeError("simulated COPASI segfault")


@pytest.fixture
def patched_adapters(monkeypatch):
    """Replace the UTC + SS adapter Step classes used by the runner."""
    import pbg_biomodels.steps.simulator_runner as mod
    monkeypatch.setattr(mod, "_UTC_CLASS_FOR", lambda name: _StubUTC, raising=True)
    monkeypatch.setattr(mod, "_SS_CLASS_FOR",  lambda name: _StubSS,  raising=True)
    return mod


def test_runner_dispatches_utc_and_steady_state(patched_adapters):
    from pbg_biomodels.steps.simulator_runner import SimulatorRunnerStep
    step = SimulatorRunnerStep(
        config={"simulator_name": "copasi"}, core=allocate_core()
    )
    out = step.update({"models": {
        "BIOMD0000000001": {
            "sbml_path": "/tmp/m.xml",
            "sedml_jobs": [
                {"name": "utc1", "kind": "utc",
                 "time": 1.0, "n_points": 3},
                {"name": "ss",   "kind": "steady_state",
                 "time": None, "n_points": None},
            ],
        }
    }})
    results = out["results"]
    bid_results = results["BIOMD0000000001"]
    assert set(bid_results.keys()) == {"utc1", "ss"}
    assert bid_results["utc1"]["kind"] == "utc"
    assert bid_results["utc1"]["time"] == [0.0, 0.5, 1.0]
    assert bid_results["utc1"]["observables"]["A"] == [1.0, 0.6, 0.3]
    assert bid_results["utc1"]["observables"]["B"] == [0.0, 0.4, 0.7]
    assert bid_results["ss"]["kind"] == "steady_state"
    assert bid_results["ss"]["time"] is None
    assert bid_results["ss"]["observables"] == {"A": 0.25, "B": 0.75}


def test_runner_records_per_job_failure(patched_adapters, monkeypatch):
    """A simulator exception is recorded as `{kind, error}` for that job
    and does not abort the runner's other jobs."""
    import pbg_biomodels.steps.simulator_runner as mod
    monkeypatch.setattr(mod, "_UTC_CLASS_FOR", lambda name: _RaisingUTC)
    from pbg_biomodels.steps.simulator_runner import SimulatorRunnerStep

    step = SimulatorRunnerStep(
        config={"simulator_name": "copasi"}, core=allocate_core()
    )
    out = step.update({"models": {
        "BIOMD0000000001": {
            "sbml_path": "/tmp/m.xml",
            "sedml_jobs": [
                {"name": "utc1", "kind": "utc", "time": 1.0, "n_points": 3},
                {"name": "ss",   "kind": "steady_state",
                 "time": None, "n_points": None},
            ],
        }
    }})
    bid_results = out["results"]["BIOMD0000000001"]
    assert bid_results["utc1"]["kind"] == "utc"
    assert "error" in bid_results["utc1"]
    assert "simulated COPASI segfault" in bid_results["utc1"]["error"]
    # The other job still ran.
    assert bid_results["ss"]["kind"] == "steady_state"
    assert bid_results["ss"]["observables"] == {"A": 0.25, "B": 0.75}


def test_runner_writes_one_branch_per_biomodel(patched_adapters):
    """A runner over two biomodels writes both branches into results."""
    from pbg_biomodels.steps.simulator_runner import SimulatorRunnerStep
    step = SimulatorRunnerStep(
        config={"simulator_name": "copasi"}, core=allocate_core()
    )
    out = step.update({"models": {
        "BIOMD0000000001": {
            "sbml_path":  "/tmp/m1.xml",
            "sedml_jobs": [{"name": "utc1", "kind": "utc",
                            "time": 1.0, "n_points": 3}],
        },
        "BIOMD0000000002": {
            "sbml_path":  "/tmp/m2.xml",
            "sedml_jobs": [{"name": "utc1", "kind": "utc",
                            "time": 1.0, "n_points": 3}],
        },
    }})
    assert set(out["results"].keys()) == {"BIOMD0000000001", "BIOMD0000000002"}


def test_runner_rejects_unknown_simulator():
    from pbg_biomodels.steps.simulator_runner import SimulatorRunnerStep
    with pytest.raises(ValueError, match="unknown simulator"):
        SimulatorRunnerStep(
            config={"simulator_name": "fake-sim"}, core=allocate_core()
        ).update({"models": {}})
