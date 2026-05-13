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
    make_utc_step_state,
)


# The pbsim_common addresses are the canonical local-Python UTC Steps.
# Override either via the keyword args if you've registered alternates.
COPASI_STEP_ADDRESS = "local:pbsim_common.simulators.copasi_process.CopasiUTCStep"
TELLURIUM_STEP_ADDRESS = "local:pbsim_common.simulators.tellurium_process.TelluriumUTCStep"
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

    state: Dict[str, Any] = {
        "species_concentrations": {},
        "species_counts": {},
        "results": {},
        "comparison": {},
    }

    state.update(make_utc_step_state(copasi_key, copasi_address, sbml_path, utc))
    state.update(make_utc_step_state(tellurium_key, tellurium_address, sbml_path, utc))

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
            "global_time": ["global_time"],
        }
        state["emitter"] = {
            "_type": "step",
            "address": emitter_address,
            "config": {"emit": {k: "node" for k in emit_wires}},
            "inputs": emit_wires,
        }

    schema: Dict[str, Any] = {
        "species_concentrations": "map[float]",
        "species_counts": "map[float]",
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

    return {"schema": schema, "state": state}
