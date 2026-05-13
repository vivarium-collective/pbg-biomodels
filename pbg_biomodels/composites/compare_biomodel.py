"""Composite builder: fetch one BioModel, run it in two simulators, compare.

A composite produced by :func:`build_compare_biomodel` runs a single
**biomodel_id → load → COPASI + Tellurium → compare → visualize**
pipeline as a single process-bigraph document.

``biomodel_id`` is the only externally-supplied parameter and lives in
the composite's state as a string store. A :class:`LoadBiomodelStep`
reads it, fetches the SBML + SED-ML via the BioModels REST API, and
writes ``sbml_path``, ``time``, and ``n_points`` into downstream stores.
:class:`LocalCopasiUTCStep` and :class:`LocalTelluriumUTCStep` read
those values as runtime inputs (not config), simulate the model, and
emit ``numeric_result`` payloads into the ``results`` map. The
:class:`SimulatorComparisonStep` reads both engine results and
writes a per-species RMSE summary; :class:`CompareOverlay` (a
``@as_visualization`` Step) renders an HTML overlay of the two
trajectories plus a bucket-colored match banner.

The composite uses ``run_steps_on_init=True`` so the Step chain fires
on construction. Output stores are pre-populated with empty placeholder
shapes — required because the bigraph runtime's ``apply()`` refuses to
auto-extend ``map[numeric_result]`` with brand-new keys at write time.
"""
from __future__ import annotations

from typing import Any, Dict


# Addresses of the Step classes wired into the composite. Override these
# kwargs if you've registered local variants under different names.
LOAD_STEP_ADDRESS = "local:pbg_biomodels_bundle.steps.load_biomodel.LoadBiomodelStep"
COPASI_STEP_ADDRESS = "local:pbg_biomodels_bundle.steps.local_simulators.LocalCopasiUTCStep"
TELLURIUM_STEP_ADDRESS = "local:pbg_biomodels_bundle.steps.local_simulators.LocalTelluriumUTCStep"
COMPARISON_STEP_ADDRESS = "local:pbg_biomodels_bundle.steps.simulator_comparison.SimulatorComparisonStep"
VISUALIZATION_STEP_ADDRESS = "local:pbg_biomodels.visualizations.compare_overlay.CompareOverlay"


def build_compare_biomodel(
    biomodel_id: str,
    *,
    load_address: str = LOAD_STEP_ADDRESS,
    copasi_address: str = COPASI_STEP_ADDRESS,
    tellurium_address: str = TELLURIUM_STEP_ADDRESS,
    comparison_address: str = COMPARISON_STEP_ADDRESS,
    visualization_address: str | None = VISUALIZATION_STEP_ADDRESS,
    with_emitter: bool = True,
    emitter_address: str = "local:RAMEmitter",
) -> Dict[str, Any]:
    """Build a single-biomodel COPASI-vs-Tellurium comparison composite.

    Args:
        biomodel_id: BioModels identifier (e.g. ``"BIOMD0000000001"``). Seeded
            into the composite's ``biomodel_id`` store and read at runtime by
            :class:`LoadBiomodelStep`.
        with_emitter: if True (default), attach a ``RAMEmitter`` collecting
            both engine results and the comparison output so
            ``gather_emitter_results`` returns the history after the run.
        visualization_address: pass ``None`` to skip the overlay viz Step
            (e.g. for headless / batch use).

    Returns:
        A composite document ``{"schema", "state", "run_steps_on_init"}``
        ready to feed ``process_bigraph.Composite``.
    """
    copasi_key = "copasi"
    tellurium_key = "tellurium"

    empty_numeric: Dict[str, Any] = {"time": [], "columns": [], "values": []}
    state: Dict[str, Any] = {
        # Inputs / intermediate stores. biomodel_id is the entry point.
        "biomodel_id": biomodel_id,
        "sbml_path":   "",
        "sim_time":    0.0,
        "n_points":    0,
        # Pre-populated map keys: bigraph apply() won't auto-extend
        # map[numeric_result] with new keys, so the simulator outputs
        # need a target slot to land in.
        "results": {
            copasi_key:    dict(empty_numeric),
            tellurium_key: dict(empty_numeric),
        },
        "comparison": {},
    }

    state["load"] = {
        "_type": "step",
        "address": load_address,
        "config": {},
        "inputs":  {"biomodel_id": ["biomodel_id"]},
        "outputs": {
            "sbml_path": ["sbml_path"],
            "time":      ["sim_time"],
            "n_points":  ["n_points"],
        },
    }

    sim_inputs = {
        "model_source": ["sbml_path"],
        "time":         ["sim_time"],
        "n_points":     ["n_points"],
    }
    state[f"{copasi_key}_step"] = {
        "_type": "step",
        "address": copasi_address,
        "config": {},
        "inputs":  sim_inputs,
        "outputs": {"result": ["results", copasi_key]},
    }
    state[f"{tellurium_key}_step"] = {
        "_type": "step",
        "address": tellurium_address,
        "config": {},
        "inputs":  sim_inputs,
        "outputs": {"result": ["results", tellurium_key]},
    }

    state["compare"] = {
        "_type": "step",
        "address": comparison_address,
        "config": {"engine_a_name": copasi_key, "engine_b_name": tellurium_key},
        "inputs": {
            "engine_a_result": ["results", copasi_key],
            "engine_b_result": ["results", tellurium_key],
        },
        "outputs": {"comparison": ["comparison"]},
    }

    if visualization_address:
        state["overlay_viz"] = {
            "_type": "step",
            "address": visualization_address,
            "config": {"title": f"{biomodel_id} — COPASI vs Tellurium overlay"},
            "inputs": {
                "engine_a_result": ["results", copasi_key],
                "engine_b_result": ["results", tellurium_key],
                "comparison":      ["comparison"],
            },
            "outputs": {"html": ["viz_html"]},
        }
        state["viz_html"] = ""

    if with_emitter:
        emit_wires = {
            "results":    ["results"],
            "comparison": ["comparison"],
        }
        state["emitter"] = {
            "_type": "step",
            "address": emitter_address,
            "config": {"emit": {k: "node" for k in emit_wires}},
            "inputs": emit_wires,
        }

    schema: Dict[str, Any] = {
        "biomodel_id": "string",
        "sbml_path":   "string",
        "sim_time":    "float",
        "n_points":    "integer",
        "results":     "map[numeric_result]",
        "comparison": {
            "n_shared":         "integer",
            "rmse_by_species":  "map[float]",
            "nrmse_by_species": "map[float]",
            "mean_nrmse":       "maybe[float]",
            "bucket":           "string",
            "bucket_label":     "string",
        },
        "viz_html": "string",
    }

    return {"schema": schema, "state": state, "run_steps_on_init": True}
