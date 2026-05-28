"""`LoadBiomodelStep` emits a `sedml_jobs` list alongside `sbml_path`,
covering every UTC + SteadyState task in the SED-ML.
"""
import pytest
from process_bigraph import allocate_core

from pbg_biomodels.steps.load_biomodel import LoadBiomodelStep


def test_outputs_declare_sedml_jobs():
    """The step's output schema includes the new `sedml_jobs` port."""
    step = LoadBiomodelStep(core=allocate_core())
    outs = step.outputs()
    assert "sbml_path" in outs
    assert "sedml_jobs" in outs
    assert outs["sedml_jobs"] == "list[tree]"
    # Back-compat ports stay (populated from the first UTC job).
    assert "time" in outs
    assert "n_points" in outs


@pytest.mark.network
def test_emits_sedml_jobs_for_real_biomodel(tmp_path, monkeypatch):
    """End-to-end: a real BioModels id parses into at least one UTC job.

    Network-gated: only run when `BIOMODELS_NETWORK_TESTS=1` is set so
    CI without network access doesn't fail.
    """
    import os
    if not os.environ.get("BIOMODELS_NETWORK_TESTS"):
        pytest.skip("set BIOMODELS_NETWORK_TESTS=1 to run network tests")

    monkeypatch.chdir(tmp_path)
    step = LoadBiomodelStep(core=allocate_core())
    out = step.update({"biomodel_id": "BIOMD0000000001"})
    assert isinstance(out["sbml_path"], str) and out["sbml_path"].endswith(".xml")
    jobs = out["sedml_jobs"]
    assert isinstance(jobs, list) and len(jobs) >= 1
    assert all("kind" in j and "name" in j for j in jobs)
    assert any(j["kind"] == "utc" for j in jobs)
