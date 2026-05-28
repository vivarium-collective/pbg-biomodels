"""End-to-end: build the batch composite with stubbed adapters + a stubbed
LoadBiomodelStep, run it via process_bigraph.Composite, and assert that
results + comparisons + viz_html populate as expected.

Stubs are real `process_bigraph.Step` subclasses; the LoadBiomodelStep
stub is swapped into `core.link_registry` because `local:<dotted>`
addresses resolve through that registry, not via runtime module import.
The runner's `_UTC_CLASS_FOR` / `_SS_CLASS_FOR` lookups ARE module-level
functions called inside the runner's update(), so monkeypatching those
attributes works directly.
"""
from typing import Any, ClassVar, Dict

import pytest
from process_bigraph import Step


_FAKE_UTC_PAYLOAD = {
    "result": {
        "time":    [0.0, 0.5, 1.0],
        "columns": ["A", "B"],
        "values":  [[1.0, 0.0], [0.6, 0.4], [0.3, 0.7]],
    }
}


_FAKE_SS_PAYLOAD = {
    "result": {
        "kind":        "steady_state",
        "time":        None,
        "observables": {"A": 0.5, "B": 0.5},
    }
}


class _StubLoad(Step):
    """Replaces LoadBiomodelStep — no network, returns canned jobs."""

    config_schema: ClassVar[Dict[str, Any]] = {}

    def inputs(self) -> Dict[str, str]:
        return {"biomodel_id": "string"}

    def outputs(self) -> Dict[str, str]:
        return {
            "sbml_path":  "string",
            "sedml_jobs": "list[tree]",
            "time":       "float",
            "n_points":   "integer",
        }

    def update(self, state: Dict[str, Any]) -> Dict[str, Any]:
        bid = state.get("biomodel_id") or ""
        return {
            "sbml_path":  f"/tmp/{bid}.xml",
            "sedml_jobs": [
                {"name": "sim1", "kind": "utc", "time": 1.0, "n_points": 3},
                {"name": "ss",   "kind": "steady_state",
                 "time": None, "n_points": None},
            ],
            "time":       1.0,
            "n_points":   3,
        }


class _StubUTC:
    """Plain stub for the runner's UTC adapter (not a Step — the runner
    instantiates it directly inside its update(), not via core)."""
    def __init__(self, config=None, core=None):
        pass
    def update(self, _state):
        return _FAKE_UTC_PAYLOAD


class _StubSS:
    """Plain stub for the runner's SS adapter."""
    def __init__(self, config=None, core=None):
        pass
    def update(self, _state):
        return _FAKE_SS_PAYLOAD


def test_end_to_end_populates_results_and_comparisons(monkeypatch):
    from process_bigraph import Composite, gather_emitter_results

    from pbg_biomodels import register_types
    from pbg_biomodels.core import build_core
    from pbg_superpowers.composite_generator import _REGISTRY, build_generator
    import pbg_biomodels.composites.batch_compare_biomodels  # noqa: F401
    import pbg_biomodels.steps.simulator_runner as runner_mod

    # Patch the runner's module-level adapter lookups — those ARE called
    # inside the runner's update(), so monkeypatch.setattr works directly.
    monkeypatch.setattr(runner_mod, "_UTC_CLASS_FOR", lambda name: _StubUTC)
    monkeypatch.setattr(runner_mod, "_SS_CLASS_FOR",  lambda name: _StubSS)

    # Build the core, register types, then swap the LoadBiomodelStep
    # registration. `local:<dotted>` addresses are resolved via
    # core.link_registry (a plain dict), so we register the stub under the
    # same dotted name the generator references.
    core = register_types(build_core())
    core.register_link(
        "pbg_biomodels.steps.load_biomodel.LoadBiomodelStep", _StubLoad
    )

    entry = next(e for e in _REGISTRY.values()
                 if e.name == "batch-compare-biomodels")
    doc = build_generator(entry, overrides={
        "biomodel_ids": ["BIOMD0000000001"],
        "simulators":   ["copasi", "tellurium"],
    })
    composite = Composite(doc, core=core)
    composite.run(0.0)

    snap = (gather_emitter_results(composite).get(("emitter",)) or [{}])[-1]
    results = snap["results"]
    comparisons = snap["comparisons"]
    viz_html = snap.get("viz_html") or ""

    # Schema: results[sim][bid][sedml_doc] = simulation_result.
    # Both simulators produced sim1 (UTC) and ss (SS) for BIOMD0000000001.
    for sim in ("copasi", "tellurium"):
        bid_result = results[sim]["BIOMD0000000001"]
        assert "sim1" in bid_result
        assert bid_result["sim1"]["kind"] == "utc"
        assert "ss" in bid_result
        assert bid_result["ss"]["kind"] == "steady_state"

    # Comparisons: comparisons[bid][sedml_doc] — one per sedml doc,
    # all-pairs across simulators.
    bid_cmp = comparisons["BIOMD0000000001"]
    assert "sim1" in bid_cmp and "ss" in bid_cmp
    assert set(bid_cmp["sim1"]["engines"]) == {"copasi", "tellurium"}
    assert bid_cmp["sim1"]["bucket"] == "good"
    assert set(bid_cmp["ss"]["engines"]) == {"copasi", "tellurium"}
    assert bid_cmp["ss"]["bucket"] == "good"

    # Viz produced non-empty HTML containing the biomodel id.
    assert "BIOMD0000000001" in viz_html
