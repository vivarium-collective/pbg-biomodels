"""Bigraph-schema types for the batch-compare-biomodels composite.

`results` is the per-(biomodel, sedml-job, simulator) leaf written by
`SimulatorRunnerStep`: a flat `map[observable -> timeseries]`. UTC jobs carry
their sample times under the reserved key `time`; steady-state jobs omit `time`
and store each observable as a length-1 list. See `viva_biomodels.result_leaf`
for the accessors that classify and unpack a leaf.

The full results store is nested `biomodel_id > sedml_job_id > simulator >
results` (`biomodel_results`). The simulator is the *innermost* key so each
per-simulator runner writes a disjoint `results[bid][job][sim]` slice and the
`tree` apply deep-merges them.

`biomodel_jobs` is the per-biomodel record written by `LoadBiomodelStep` —
the SBML path plus the list of simulation tasks parsed out of the SED-ML
(each task is a free-form tree with `name`, `kind`, optional `time`,
optional `n_points`).

`simulation_result` / `sim_results_per_biomodel` are the LEGACY leaf and store
shapes (simulator-outermost, with explicit `kind`/`time`/`observables`). They
remain registered for back-compat with the legacy `compare-biomodel` flow but
are no longer produced by the batch composite.
"""
from __future__ import annotations


SIMULATION_TYPES = {
    # New leaf: observable -> timeseries (time under the reserved "time" key).
    "results": "map[list[float]]",
    # New nested store: biomodel_id -> sedml_job_id -> simulator -> results.
    "biomodel_results": "map[map[map[results]]]",
    # Legacy leaf + store (simulator-outermost), kept for `compare-biomodel`.
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
