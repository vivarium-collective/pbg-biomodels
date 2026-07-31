"""The batch-compare schema registers the new `results` leaf and
`biomodel_results` store, plus the legacy `simulation_result`, `biomodel_jobs`,
and `sim_results_per_biomodel` types, so composites can wire stores by name.
"""
from process_bigraph import allocate_core

from viva_biomodels import register_types


def _core():
    return register_types(allocate_core())


def test_results_leaf_type_registered():
    core = _core()
    # The new leaf: a flat map[observable -> timeseries].
    schema = core.access("results")
    assert schema is not None


def test_biomodel_results_store_type_registered():
    core = _core()
    # biomodel_id > sedml_job_id > simulator > results.
    schema = core.access("biomodel_results")
    assert schema is not None


def test_simulation_result_type_registered():
    core = _core()
    # access_schema returns the resolved schema for a registered type name;
    # raises KeyError-ish if missing.
    schema = core.access("simulation_result")
    assert schema is not None
    assert "kind" in schema or "_type" in schema  # records are dict-shaped


def test_biomodel_jobs_type_registered():
    core = _core()
    schema = core.access("biomodel_jobs")
    assert schema is not None


def test_sim_results_per_biomodel_alias_registered():
    core = _core()
    schema = core.access("sim_results_per_biomodel")
    assert schema is not None
