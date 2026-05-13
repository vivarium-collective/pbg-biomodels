"""Composite builder: fetch one BioModel, run it in two simulators, compare.

A composite produced by :func:`build_compare_biomodel` runs the named
BioModel under both COPASI and Tellurium (via the UTC Steps that live in
``pbsim_common``), feeds both engines' trajectories into the bundle's
``SimulatorComparisonStep``, and renders an overlay visualization showing
both traces per species plus the match summary.

Biomodel-ID is a **builder parameter**, not a runtime composite input —
the two UTC Steps require ``model_source`` in their config (set at
composite-construction time), so different BioModels mean different
composite documents. Build one composite per ID; iterate the builder
across the BioModels corpus.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import biomodels

from pbg_biomodels_bundle.run_biomodels import (
    BiomodelLoadResult,
    load_biomodel,
)


# The bundle's Local* UTC Steps declare empty inputs() so they fire on
# composite startup. The earlier `pbsim_common.*UTCStep` addresses needed
# their species_concentrations / species_counts input stores to change
# before firing, which nothing in the composite ever did — so the Steps
# never triggered and `results` stayed empty.
COPASI_STEP_ADDRESS = "local:pbg_biomodels_bundle.steps.local_simulators.LocalCopasiUTCStep"
TELLURIUM_STEP_ADDRESS = "local:pbg_biomodels_bundle.steps.local_simulators.LocalTelluriumUTCStep"
COMPARISON_STEP_ADDRESS = "local:pbg_biomodels_bundle.steps.simulator_comparison.SimulatorComparisonStep"
VISUALIZATION_STEP_ADDRESS = "local:pbg_biomodels.visualizations.compare_overlay.CompareOverlay"


def build_compare_biomodel(
    biomodel_id: str,
    *,
    copasi_address: str = COPASI_STEP_ADDRESS,
    tellurium_address: str = TELLURIUM_STEP_ADDRESS,
    comparison_address: str = COMPARISON_STEP_ADDRESS,
    visualization_address: Optional[str] = VISUALIZATION_STEP_ADDRESS,
    with_emitter: bool = True,
    emitter_address: str = "local:RAMEmitter",
    load_result: Optional[BiomodelLoadResult] = None,
) -> Dict[str, Any]:
    """Build a single-biomodel COPASI-vs-Tellurium comparison composite.

    Args:
        biomodel_id: BioModels identifier (e.g. ``"BIOMD0000000001"``).
        with_emitter: if True (default), attach a RAMEmitter collecting both
            engine results and the comparison output, so a post-run
            ``gather_emitter_results`` returns the history for inspection.
        load_result: pre-fetched ``BiomodelLoadResult`` — pass to skip the
            biomodels API call (useful in tests).

    Returns:
        A ``{"schema": ..., "state": ...}`` document ready to feed
        ``process_bigraph.Composite``.
    """
    if load_result is None:
        meta = biomodels.get_metadata(biomodel_id)
        load_result = load_biomodel(biomodel_id, meta)

    sbml_path = os.path.abspath(load_result.sbml_path)
    utc = load_result.utc

    copasi_key = f"{biomodel_id}_copasi"
    tellurium_key = f"{biomodel_id}_tellurium"

    # Pre-populate the `results` map with placeholder entries for each
    # engine. The Steps write into `results[<engine_key>]`; without a
    # pre-existing key the bigraph runtime's apply() won't auto-extend the
    # map and the output is silently dropped.
    empty_numeric: Dict[str, Any] = {"time": [], "columns": [], "values": []}
    state: Dict[str, Any] = {
        "results": {
            copasi_key:    dict(empty_numeric),
            tellurium_key: dict(empty_numeric),
        },
        "comparison": {},
    }

    # Local* Steps declare no inputs, so the only wires they need are
    # outputs. Each writes a numeric_result into results[<engine_key>].
    sim_config = {
        "model_source": sbml_path,
        "time": float(utc.duration),
        "n_points": int(utc.number_of_points),
    }
    state[f"{copasi_key}_step"] = {
        "_type": "step",
        "address": copasi_address,
        "config": sim_config,
        "outputs": {"result": ["results", copasi_key]},
    }
    state[f"{tellurium_key}_step"] = {
        "_type": "step",
        "address": tellurium_address,
        "config": sim_config,
        "outputs": {"result": ["results", tellurium_key]},
    }

    state["compare"] = {
        "_type": "step",
        "address": comparison_address,
        "config": {"engine_a_name": "copasi", "engine_b_name": "tellurium"},
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
            "config": {
                "title": f"{biomodel_id} — COPASI vs Tellurium overlay",
                "engine_a_name": "copasi",
                "engine_b_name": "tellurium",
            },
            "inputs": {
                "engine_a_result": ["results", copasi_key],
                "engine_b_result": ["results", tellurium_key],
                "comparison": ["comparison"],
            },
            "outputs": {"html": ["viz_html"]},
        }
        state["viz_html"] = ""

    if with_emitter:
        emit_wires = {
            "results": ["results"],
            "comparison": ["comparison"],
        }
        state["emitter"] = {
            "_type": "step",
            "address": emitter_address,
            "config": {"emit": {k: "node" for k in emit_wires}},
            "inputs": emit_wires,
        }

    schema: Dict[str, Any] = {
        "results": "map[numeric_result]",
        # Mirrors SimulatorComparisonStep.outputs() so the store accepts
        # the Step's update payload without coercion.
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

    # `run_steps_on_init=True` is required: our Local* simulator Steps
    # declare no inputs and rely on initial firing rather than input-change
    # triggering. The Composite default is False, so without this flag the
    # Steps never execute and `results` stays empty.
    return {"schema": schema, "state": state, "run_steps_on_init": True}
