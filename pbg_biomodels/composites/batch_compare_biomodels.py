"""Composite generator: batch-compare-biomodels.

For each biomodel id, fetch the SBML + parse the SED-ML once into a
`biomodel_jobs` record under `models[bid]`. For each requested simulator,
one `SimulatorRunnerStep` iterates `models` and writes its slice of
`results[sim]`. A single `BatchCompareStep` consumes the full nested
`results` and writes `comparisons`. A single `BatchCompareOverlay` viz
renders the HTML.

Distinct from the legacy `compare-biomodel`:
* one Step per simulator, not per (simulator × biomodel);
* nested `results[sim][bid][sedml_doc]` instead of flat suffixed keys
  (sim is outermost because each per-simulator runner writes its bid-
  keyed slice into `results[<sim>]`);
* supports steady-state tasks (kind="steady_state");
* supports multiple SED-ML simulations per biomodel.

The legacy `compare-biomodel` generator is preserved untouched.
"""
from __future__ import annotations

from typing import Any, Dict, List

from pbg_superpowers.composite_generator import composite_generator

from pbg_biomodels.simulators import resolve_simulators


LOAD_STEP_ADDRESS    = "local:pbg_biomodels.steps.load_biomodel.LoadBiomodelStep"
RUNNER_STEP_ADDRESS  = "local:pbg_biomodels.steps.simulator_runner.SimulatorRunnerStep"
COMPARE_STEP_ADDRESS = "local:pbg_biomodels.steps.simulator_comparison.BatchCompareStep"
VIZ_STEP_ADDRESS     = "local:pbg_biomodels.visualizations.batch_compare_overlay.BatchCompareOverlay"


@composite_generator(
    name="batch-compare-biomodels",
    description=(
        "For each BioModel id, fetch the SBML, parse every SED-ML simulation "
        "(UTC + steady-state), then run each simulator over all jobs via a "
        "single per-simulator runner Step. Comparison reads the full nested "
        "results store and produces all-pairs nRMSE per (biomodel, sedml-doc)."
    ),
    parameters={
        "biomodel_ids": {
            "type": "list[string]",
            "default": ["BIOMD0000000001"],
            "description": (
                "BioModels identifiers, one per line. Each id gets one "
                "LoadBiomodelStep that writes into `models[<id>]`."
            ),
        },
        "simulators": {
            "type": "list[string]",
            "default": ["copasi", "tellurium", "simbio"],
            "description": (
                "Simulators to run, one per line. Allowed values: "
                "copasi, tellurium, simbio. One SimulatorRunnerStep "
                "is created per entry; the runner iterates `models` "
                "and dispatches each job to its UTC or steady-state "
                "adapter."
            ),
        },
    },
    default_n_steps=1,
)
def build_batch_compare_biomodels(
    core: Any = None,
    *,
    biomodel_ids: List[str],
    simulators: List[str],
    with_emitter: bool = True,
    emitter_address: str = "local:RAMEmitter",
) -> Dict[str, Any]:
    sims = resolve_simulators(simulators)

    state: Dict[str, Any] = {
        "models":      {bid: {"sbml_path": "", "sedml_jobs": []}
                        for bid in biomodel_ids},
        "results":     {sim: {bid: {} for bid in biomodel_ids}
                        for sim in sims},
        "comparisons": {bid: {} for bid in biomodel_ids},
        "viz_html":    "",
    }

    for bid in biomodel_ids:
        state[f"biomodel_id_{bid}"] = bid
        state[f"load_{bid}"] = {
            "_type":   "step",
            "address": LOAD_STEP_ADDRESS,
            "config":  {},
            "inputs":  {"biomodel_id": [f"biomodel_id_{bid}"]},
            "outputs": {
                "sbml_path":  ["models", bid, "sbml_path"],
                "sedml_jobs": ["models", bid, "sedml_jobs"],
            },
        }

    for sim in sims:
        state[f"runner_{sim}"] = {
            "_type":   "step",
            "address": RUNNER_STEP_ADDRESS,
            "config":  {"simulator_name": sim},
            "inputs":  {"models": ["models"]},
            "outputs": {"results": ["results", sim]},
        }

    state["compare"] = {
        "_type":   "step",
        "address": COMPARE_STEP_ADDRESS,
        "config":  {},
        "inputs":  {"results": ["results"]},
        "outputs": {"comparisons": ["comparisons"]},
    }

    state["batch_overlay_viz"] = {
        "_type":   "step",
        "address": VIZ_STEP_ADDRESS,
        "config":  {
            "title":        "BioModels: batch comparison",
            "biomodel_ids": list(biomodel_ids),
        },
        "inputs":  {"results": ["results"], "comparisons": ["comparisons"]},
        "outputs": {"html": ["viz_html"]},
    }

    if with_emitter:
        state["emitter"] = {
            "_type":   "step",
            "address": emitter_address,
            "config":  {"emit": {
                "models":      "node",
                "results":     "node",
                "comparisons": "node",
                "viz_html":    "string",
            }},
            "inputs":  {
                "models":      ["models"],
                "results":     ["results"],
                "comparisons": ["comparisons"],
                "viz_html":    ["viz_html"],
            },
        }

    return {"state": state, "run_steps_on_init": True}
