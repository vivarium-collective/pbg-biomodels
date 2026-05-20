"""Build the multi-simulator comparison composite.

For each BioModel id, fetch the SBML, run it under each selected simulator
(plus any external reference CSVs treated as engines), and score every pair
of engines with an all-pairs nRMSE matrix.

``build_compare_document`` is the rich builder driven by the CLI (arbitrary
simulator lists + per-biomodel reference CSVs). A thin ``@composite_generator``
(``compare-simulators``) exposes the common case to the dashboard.

Per-biomodel state is held in flat top-level keys suffixed by the biomodel id
(``sbml_path_<bid>``, ``copasi_<bid>``, ``comparison_<bid>``, …) so every wire
is a one-segment path — the same convention as ``compare_biomodel``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from pbg_superpowers.composite_generator import composite_generator

from pbg_biomodels.simulators import resolve_simulators, utc_step_address

LOAD_STEP_ADDRESS = "local:pbg_biomodels.steps.load_biomodel.LoadBiomodelStep"
REFERENCE_STEP_ADDRESS = "local:pbg_biomodels.steps.reference_data.ReferenceDataStep"
COMPARISON_STEP_ADDRESS = (
    "local:pbg_biomodels.steps.simulator_comparison.MultiSimulatorComparisonStep"
)


def _empty_numeric() -> Dict[str, Any]:
    return {"time": [], "columns": [], "values": []}


def build_compare_document(
    biomodel_ids: List[str],
    simulators="all",
    references: Optional[Mapping[str, Mapping[str, str]]] = None,
    *,
    with_emitter: bool = True,
    emitter_address: str = "local:RAMEmitter",
) -> Dict[str, Any]:
    """Build the N-simulator comparison composite document.

    Args:
        biomodel_ids: BioModels identifiers; one branch per id.
        simulators: ``"all"``, a comma-separated string, or a list of simulator
            names (see :func:`pbg_biomodels.simulators.resolve_simulators`).
        references: optional ``{biomodel_id: {reference_name: csv_path}}``.
            Each reference is loaded as an engine and scored like a simulator.
        with_emitter: attach a RAMEmitter capturing every engine result and the
            comparison matrix per biomodel.

    Returns:
        ``{"state", "run_steps_on_init": True}`` ready for
        ``process_bigraph.Composite``.
    """
    sims = resolve_simulators(simulators)
    references = references or {}

    state: Dict[str, Any] = {}
    emit_schema: Dict[str, str] = {}

    for bid in biomodel_ids:
        ref_for_bid = dict(references.get(bid, {}))
        engine_names = list(sims) + list(ref_for_bid)

        # Per-biomodel stores.
        state[f"biomodel_id_{bid}"] = bid
        state[f"sbml_path_{bid}"] = ""
        state[f"sim_time_{bid}"] = 0.0
        state[f"n_points_{bid}"] = 0
        state[f"comparison_{bid}"] = {}
        for engine in engine_names:
            state[f"{engine}_{bid}"] = _empty_numeric()

        # load -> sbml_path / time / n_points
        state[f"load_{bid}"] = {
            "_type": "step",
            "address": LOAD_STEP_ADDRESS,
            "config": {},
            "inputs": {"biomodel_id": [f"biomodel_id_{bid}"]},
            "outputs": {
                "sbml_path": [f"sbml_path_{bid}"],
                "time": [f"sim_time_{bid}"],
                "n_points": [f"n_points_{bid}"],
            },
        }

        sim_inputs = {
            "model_source": [f"sbml_path_{bid}"],
            "time": [f"sim_time_{bid}"],
            "n_points": [f"n_points_{bid}"],
        }
        for sim in sims:
            state[f"{sim}_step_{bid}"] = {
                "_type": "step",
                "address": utc_step_address(sim),
                "config": {},
                "inputs": sim_inputs,
                "outputs": {"result": [f"{sim}_{bid}"]},
            }

        # Reference CSVs: each becomes an engine via ReferenceDataStep.
        for ref_name, csv_path in ref_for_bid.items():
            state[f"{ref_name}_path_{bid}"] = csv_path
            state[f"ref_{ref_name}_step_{bid}"] = {
                "_type": "step",
                "address": REFERENCE_STEP_ADDRESS,
                "config": {"csv_path": csv_path},
                "inputs": {"csv_path": [f"{ref_name}_path_{bid}"]},
                "outputs": {"result": [f"{ref_name}_{bid}"]},
            }

        # All-pairs comparison across every engine for this biomodel.
        state[f"compare_{bid}"] = {
            "_type": "step",
            "address": COMPARISON_STEP_ADDRESS,
            "config": {"engine_names": engine_names},
            "inputs": {engine: [f"{engine}_{bid}"] for engine in engine_names},
            "outputs": {"comparison": [f"comparison_{bid}"]},
        }

        for engine in engine_names:
            emit_schema[f"{engine}_{bid}"] = "node"
        emit_schema[f"comparison_{bid}"] = "node"

    if with_emitter and emit_schema:
        state["emitter"] = {
            "_type": "step",
            "address": emitter_address,
            "config": {"emit": emit_schema},
            "inputs": {k: [k] for k in emit_schema},
        }

    return {"state": state, "run_steps_on_init": True}


def run_comparison(
    biomodel_ids: List[str],
    simulators="all",
    references: Optional[Mapping[str, Mapping[str, str]]] = None,
) -> Dict[str, Any]:
    """Build, run, and collect a comparison into the report structure.

    Returns ``{biomodel_id: {"engines": {name: numeric_result}, "comparison": ...}}``
    suitable for :func:`pbg_biomodels.report.build_comparison_report`.
    """
    from process_bigraph import Composite, gather_emitter_results

    from pbg_biomodels import register_types
    from pbg_biomodels.core import build_core

    sims = resolve_simulators(simulators)
    references = references or {}

    doc = build_compare_document(biomodel_ids, simulators=sims, references=references)
    core = register_types(build_core())
    composite = Composite(doc, core=core)
    composite.run(0.0)  # Steps already ran on init; flush the emitter.

    snapshots = gather_emitter_results(composite).get(("emitter",), [])
    snap = snapshots[-1] if snapshots else {}

    results: Dict[str, Any] = {}
    for bid in biomodel_ids:
        engine_names = list(sims) + list(references.get(bid, {}))
        engines = {name: snap.get(f"{name}_{bid}", {}) for name in engine_names}
        results[bid] = {
            "engines": engines,
            "comparison": snap.get(f"comparison_{bid}", {}),
        }
    return results


@composite_generator(
    name="compare-simulators",
    description=(
        "For each BioModel id, run it under every selected simulator and score "
        "all pairs with an nRMSE matrix. (Reference CSV datasets are supported "
        "via the CLI: `pbg-biomodels compare`.)"
    ),
    parameters={
        "biomodel_ids": {
            "type": "list[string]",
            "default": ["BIOMD0000000001"],
            "description": "BioModels identifiers, one per line.",
        },
        "simulators": {
            "type": "string",
            "default": "all",
            "description": "Comma-separated simulator names, or 'all'.",
        },
    },
    default_n_steps=1,
)
def build_compare_simulators(
    core: Any = None,
    *,
    biomodel_ids: List[str],
    simulators: str = "all",
) -> Dict[str, Any]:
    return build_compare_document(biomodel_ids, simulators=simulators)
