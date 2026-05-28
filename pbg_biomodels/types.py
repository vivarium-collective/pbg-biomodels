"""Bigraph-schema types for the batch-compare-biomodels composite.

`simulation_result` is the per-(biomodel, simulator, sed-ml-doc) leaf written
by `SimulatorRunnerStep`. The `kind` field tags the union: UTC payloads carry
a `time` vector and per-observable list-of-floats; steady-state payloads carry
`time=None` and per-observable scalars.

`biomodel_jobs` is the per-biomodel record written by `LoadBiomodelStep` —
the SBML path plus the list of simulation tasks parsed out of the SED-ML
(each task is a free-form tree with `name`, `kind`, optional `time`,
optional `n_points`).
"""
from __future__ import annotations


SIMULATION_TYPES = {
    "simulation_result": {
        "kind":        "string",
        "time":        "maybe[list[float]]",
        "observables": "tree",
    },
    "biomodel_jobs": {
        "sbml_path":  "string",
        "sedml_jobs": "list[tree]",
    },
    "sim_results_per_biomodel": "map[map[simulation_result]]",
}


def register_simulation_types(core):
    """Register the batch-compare types into a process-bigraph core."""
    core.register_types(SIMULATION_TYPES)
    return core
