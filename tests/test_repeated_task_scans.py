"""Repeated-task (1-D parameter-scan) support: leaf classification, SED-ML
derivation, SBML mutation, and comparison reuse.

See docs/superpowers/specs/2026-07-02-repeated-task-parameter-scans-design.md.
"""
import warnings

import libsbml
import pytest
from process_bigraph import allocate_core

from pbg_biomodels import result_leaf
from pbg_biomodels.comparison import compare_two_engines
from pbg_biomodels.run_biomodels import (
    extract_repeated_tasks,
    mutate_sbml,
    _range_values,
    _resolve_setvalue_target,
)

import libsedml


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

_SBML = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="m">
    <listOfCompartments>
      <compartment id="c" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c" initialConcentration="2.0"
               hasOnlySubstanceUnits="false" boundaryCondition="false"
               constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k1" value="1.0" constant="true"/>
    </listOfParameters>
  </model>
</sbml>
"""

_PARAM_TARGET = ("/sbml:sbml/sbml:model/sbml:listOfParameters/"
                 "sbml:parameter[@id='k1']/@value")

_SEDML = f"""<?xml version="1.0" encoding="UTF-8"?>
<sedML xmlns="http://sed-ml.org/sed-ml/level1/version3" level="1" version="3">
  <listOfSimulations>
    <uniformTimeCourse id="utc1" initialTime="0" outputStartTime="0"
                       outputEndTime="10" numberOfPoints="100">
      <algorithm kisaoID="KISAO:0000019"/>
    </uniformTimeCourse>
  </listOfSimulations>
  <listOfModels>
    <model id="model1" language="urn:sedml:language:sbml" source="model.xml"/>
  </listOfModels>
  <listOfTasks>
    <task id="task1" modelReference="model1" simulationReference="utc1"/>
    <repeatedTask id="scan1" resetModel="true" range="current">
      <listOfRanges>
        <uniformRange id="current" start="0" end="5" numberOfPoints="6"
                      type="linear"/>
      </listOfRanges>
      <listOfChanges>
        <setValue target="{_PARAM_TARGET}" range="current"
                  modelReference="model1">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <ci>current</ci>
          </math>
        </setValue>
      </listOfChanges>
      <listOfSubTasks>
        <subTask order="1" task="task1"/>
      </listOfSubTasks>
    </repeatedTask>
  </listOfTasks>
</sedML>
"""

# A 1-D vectorRange scan with an IMPLICIT setValue attribute (target stops at
# the element, no trailing /@value) — the shape real BioModels SED-ML uses
# (e.g. BIOMD0000001077's epo_level scan).
_SEDML_VECTOR = """<?xml version="1.0" encoding="UTF-8"?>
<sedML xmlns="http://sed-ml.org/sed-ml/level1/version3" level="1" version="3">
  <listOfSimulations>
    <uniformTimeCourse id="utc1" initialTime="0" outputStartTime="0"
                       outputEndTime="10" numberOfPoints="100">
      <algorithm kisaoID="KISAO:0000019"/>
    </uniformTimeCourse>
  </listOfSimulations>
  <listOfModels>
    <model id="model1" language="urn:sedml:language:sbml" source="model.xml"/>
  </listOfModels>
  <listOfTasks>
    <task id="task1" modelReference="model1" simulationReference="utc1"/>
    <repeatedTask id="vscan" resetModel="true" range="lvl">
      <listOfRanges>
        <vectorRange id="lvl">
          <value>5</value><value>0</value>
        </vectorRange>
      </listOfRanges>
      <listOfChanges>
        <setValue target="/sbml:sbml/sbml:model/sbml:listOfParameters/sbml:parameter[@id='k1']"
                  range="lvl" modelReference="model1">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>lvl</ci></math>
        </setValue>
      </listOfChanges>
      <listOfSubTasks>
        <subTask order="1" task="task1"/>
      </listOfSubTasks>
    </repeatedTask>
  </listOfTasks>
</sedML>
"""

# A repeatedTask with two ranges -> must be skipped (nested/2-D, out of scope).
_SEDML_NESTED = """<?xml version="1.0" encoding="UTF-8"?>
<sedML xmlns="http://sed-ml.org/sed-ml/level1/version3" level="1" version="3">
  <listOfSimulations>
    <uniformTimeCourse id="utc1" initialTime="0" outputStartTime="0"
                       outputEndTime="10" numberOfPoints="100">
      <algorithm kisaoID="KISAO:0000019"/>
    </uniformTimeCourse>
  </listOfSimulations>
  <listOfModels>
    <model id="model1" language="urn:sedml:language:sbml" source="model.xml"/>
  </listOfModels>
  <listOfTasks>
    <task id="task1" modelReference="model1" simulationReference="utc1"/>
    <repeatedTask id="scan2d" resetModel="true" range="outer">
      <listOfRanges>
        <uniformRange id="outer" start="0" end="2" numberOfPoints="3"
                      type="linear"/>
        <uniformRange id="inner" start="0" end="1" numberOfPoints="2"
                      type="linear"/>
      </listOfRanges>
      <listOfSubTasks>
        <subTask order="1" task="task1"/>
      </listOfSubTasks>
    </repeatedTask>
  </listOfTasks>
</sedML>
"""


def _sed_doc(text):
    doc = libsedml.readSedMLFromString(text)
    assert doc.getNumErrors(libsedml.LIBSEDML_SEV_ERROR) == 0, (
        "\n".join(doc.getError(i).getMessage()
                  for i in range(doc.getNumErrors()))
    )
    return doc


# --------------------------------------------------------------------------
# result_leaf: three-way classification
# --------------------------------------------------------------------------

def test_scan_leaf_classified_as_repeated_task():
    leaf = {"scan": [0.0, 1.0, 2.0], "A": [2.0, 1.5, 1.0]}
    assert result_leaf.is_scan(leaf)
    assert not result_leaf.is_utc(leaf)
    assert result_leaf.kind_of(leaf) == "repeated_task"


def test_utc_and_steady_state_unaffected():
    utc = {"time": [0.0, 1.0], "A": [2.0, 1.0]}
    ss = {"A": [3.0]}
    assert result_leaf.kind_of(utc) == "utc"
    assert result_leaf.kind_of(ss) == "steady_state"


def test_axis_of_and_observables_exclude_scan():
    leaf = {"scan": [0.0, 1.0, 2.0], "A": [2.0, 1.5, 1.0]}
    name, values = result_leaf.axis_of(leaf)
    assert name == "scan"
    assert values == [0.0, 1.0, 2.0]
    assert "scan" not in result_leaf.observables_of(leaf)
    assert set(result_leaf.observables_of(leaf)) == {"A"}


def test_to_numeric_result_uses_scan_axis():
    leaf = {"scan": [0.0, 1.0, 2.0], "A": [2.0, 1.5, 1.0]}
    nr = result_leaf.to_numeric_result(leaf)
    assert nr["time"] == [0.0, 1.0, 2.0]   # axis carried under "time"
    assert nr["columns"] == ["A"]
    assert nr["values"] == [[2.0], [1.5], [1.0]]


def test_kind_of_warns_on_both_axes():
    with pytest.warns(UserWarning):
        assert result_leaf.kind_of({"time": [0.0], "scan": [0.0], "A": [1.0]}) == "utc"


# --------------------------------------------------------------------------
# SED-ML derivation
# --------------------------------------------------------------------------

def test_range_values_uniform_linear():
    doc = _sed_doc(_SEDML)
    task = doc.getTask(doc.getNumTasks() - 1)
    rng = task.getRange("current")
    assert _range_values(rng) == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]


def test_resolve_setvalue_target():
    assert _resolve_setvalue_target(_PARAM_TARGET) == ("k1", "value")
    assert _resolve_setvalue_target("no-attr-here") is None
    # implicit attribute: target stops at the element (real-world common case)
    assert _resolve_setvalue_target(
        "/sbml:sbml/sbml:model/sbml:listOfParameters/sbml:parameter[@id='epo']"
    ) == ("epo", None)


def test_range_values_vector():
    doc = _sed_doc(_SEDML_VECTOR)
    task = doc.getTask(doc.getNumTasks() - 1)
    assert _range_values(task.getRange("lvl")) == [5.0, 0.0]


def test_extract_repeated_tasks_vectorrange_implicit_attr():
    jobs = extract_repeated_tasks(_sed_doc(_SEDML_VECTOR))
    assert len(jobs) == 1
    job = jobs[0]
    assert job["param_id"] == "k1"
    assert job["param_attr"] is None            # implicit -> resolved at mutate
    assert job["scan_values"] == [5.0, 0.0]


def test_mutate_sbml_implicit_attribute_sets_parameter():
    # attribute=None -> natural quantity (parameter value)
    out = mutate_sbml(_SBML, "k1", None, 3.25)
    model = libsbml.readSBMLFromFile(out).getModel()
    assert model.getParameter("k1").getValue() == pytest.approx(3.25)


def test_extract_repeated_tasks_happy_path():
    jobs = extract_repeated_tasks(_sed_doc(_SEDML))
    assert len(jobs) == 1
    job = jobs[0]
    assert job["name"] == "scan1"
    assert job["kind"] == "repeated_task"
    assert job["param_id"] == "k1"
    assert job["param_attr"] == "value"
    assert job["scan_values"] == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    assert job["subtask"]["kind"] == "utc"


def test_extract_repeated_tasks_skips_nested_scan():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        jobs = extract_repeated_tasks(_sed_doc(_SEDML_NESTED))
    assert jobs == []
    assert any("scan2d" in str(w.message) for w in caught)


# --------------------------------------------------------------------------
# SBML mutation
# --------------------------------------------------------------------------

def test_mutate_sbml_sets_parameter_value():
    out = mutate_sbml(_SBML, "k1", "value", 7.5)
    doc = libsbml.readSBMLFromFile(out)
    model = doc.getModel()
    assert model.getParameter("k1").getValue() == pytest.approx(7.5)
    # unrelated element untouched
    assert model.getSpecies("A").getInitialConcentration() == pytest.approx(2.0)


def test_mutate_sbml_sets_species_initial_concentration():
    out = mutate_sbml(_SBML, "A", "initialConcentration", 9.0)
    model = libsbml.readSBMLFromFile(out).getModel()
    assert model.getSpecies("A").getInitialConcentration() == pytest.approx(9.0)


def test_mutate_sbml_unknown_element_raises():
    with pytest.raises(ValueError):
        mutate_sbml(_SBML, "nope", "value", 1.0)


# --------------------------------------------------------------------------
# Comparison reuse (scan curves scored by the UTC series metric)
# --------------------------------------------------------------------------

def test_identical_scan_curves_score_zero():
    a = result_leaf.to_numeric_result({"scan": [0, 1, 2], "A": [2.0, 1.5, 1.0]})
    b = result_leaf.to_numeric_result({"scan": [0, 1, 2], "A": [2.0, 1.5, 1.0]})
    result = compare_two_engines(a, b, "copasi", "tellurium")
    assert result["mean_nrmse"] == pytest.approx(0.0)


def test_shifted_scan_curve_scores_nonzero():
    a = result_leaf.to_numeric_result({"scan": [0, 1, 2], "A": [2.0, 1.5, 1.0]})
    b = result_leaf.to_numeric_result({"scan": [0, 1, 2], "A": [2.2, 1.7, 1.2]})
    result = compare_two_engines(a, b, "copasi", "tellurium")
    assert result["mean_nrmse"] > 0.0


# --------------------------------------------------------------------------
# Runner: per-scan-point mutation + endpoint reduction
# --------------------------------------------------------------------------

class _K1EndpointUTC:
    """Stub UTC engine whose endpoint value equals the model's ``k1``.

    Because the runner mutates the SBML per scan point, the endpoint this
    returns tracks the swept parameter — so the assembled response curve must
    equal the scan values.
    """

    def __init__(self, config=None, core=None):
        pass

    def update(self, state):
        model = libsbml.readSBMLFromFile(state["model_source"]).getModel()
        k1 = model.getParameter("k1").getValue()
        return {"result": {"time": [0.0, 1.0], "columns": ["A"],
                           "values": [[0.0], [k1]]}}  # endpoint A == k1


def test_runner_scan_reduces_to_response_curve(monkeypatch, tmp_path):
    import pbg_biomodels.steps.simulator_runner as mod
    monkeypatch.setattr(mod, "_UTC_CLASS_FOR", lambda name: _K1EndpointUTC)
    monkeypatch.setattr(mod, "_SS_CLASS_FOR", lambda name: _K1EndpointUTC)

    sbml = tmp_path / "m.xml"
    sbml.write_text(_SBML)

    from pbg_biomodels.steps.simulator_runner import SimulatorRunnerStep
    step = SimulatorRunnerStep(
        config={"simulator_name": "copasi"}, core=allocate_core())
    out = step.update({"models": {
        "BIOMD0000000999": {
            "sbml_path": str(sbml),
            "sedml_jobs": [{
                "name": "scan1", "kind": "repeated_task",
                "param_id": "k1", "param_attr": "value",
                "scan_values": [0.0, 1.0, 2.0],
                "subtask": {"kind": "utc", "time": 10.0, "n_points": 3},
            }],
        }
    }})

    leaf = out["results"]["BIOMD0000000999"]["scan1"]["copasi"]
    assert result_leaf.kind_of(leaf) == "repeated_task"
    assert leaf["scan"] == [0.0, 1.0, 2.0]
    # endpoint == k1 == the scan value at each point
    assert leaf["A"] == pytest.approx([0.0, 1.0, 2.0])
    rec = out["diagnostics"]["runs"]["BIOMD0000000999"]["scan1"]["copasi"]
    assert rec["status"] == "ok"


# --------------------------------------------------------------------------
# Persistence + viewer: parquet round-trip and scan-axis relabeling
# --------------------------------------------------------------------------

def test_two_tier_persists_scan_and_viewer_relabels(tmp_path):
    pytest.importorskip("pyarrow")  # two_tier is optional (no parquet in base CI)
    from pbg_biomodels.two_tier import write_model
    from pbg_biomodels import lazy_viewer

    model_results = {"scan1": {
        "copasi":    {"scan": [0.0, 1.0, 2.0], "A": [2.0, 1.5, 1.0]},
        "tellurium": {"scan": [0.0, 1.0, 2.0], "A": [2.0, 1.5, 1.0]},
    }}
    entry = write_model("BIOMD0000000999", model_results, {}, tmp_path)
    assert entry["jobs"]["scan1"]["kind"] == "repeated_task"

    # Parquet round-trip keeps the scan axis (not NaN'd like steady-state).
    leaves = lazy_viewer._parquet_leaves_aligned(
        tmp_path, "BIOMD0000000999")["scan1"]
    assert leaves["copasi"]["time"] == pytest.approx([0.0, 1.0, 2.0])
    assert leaves["copasi"]["A"] == pytest.approx([2.0, 1.5, 1.0])

    # The figure reuses the overlay but relabels the x-axis.
    fig = lazy_viewer._figure_for(
        tmp_path, "BIOMD0000000999", "scan1", kind="repeated_task")
    titles = []
    for k, ax in fig["layout"].items():
        if k.startswith("xaxis") and isinstance(ax, dict):
            t = ax.get("title")
            titles.append(t.get("text") if isinstance(t, dict) else t)
    assert "scan parameter" in titles
    assert "time" not in titles


# --------------------------------------------------------------------------
# Reference-side scan reader
# --------------------------------------------------------------------------

def _write_scan_h5(path, shape, labels):
    """Write a synthetic BioSimulators-style scan report: a rank>=3 SedReport
    dataset whose endpoint (last timepoint) for label i, scan point s is a
    deterministic i*100 + s."""
    import h5py
    import numpy as np

    n_label = shape[0]
    n_time = shape[-1]
    data = np.zeros(shape, dtype=float)
    # fill so the LAST timepoint encodes i*100 + flattened-scan-index
    flat_scan = int(np.prod(shape[1:-1]))
    for i in range(n_label):
        block = np.arange(flat_scan, dtype=float) + i * 100.0
        data[i] = block.reshape(shape[1:-1] + (1,)) * np.ones(n_time)
        data[i][..., -1] = block.reshape(shape[1:-1])  # endpoint = i*100 + s
    with h5py.File(path, "w") as f:
        grp = f.create_group("doc.sedml")
        ds = grp.create_dataset("autogen_report_for_task2", data=data)
        ds.attrs["_type"] = "SedReport"
        ds.attrs["sedmlDataSetLabels"] = labels


def test_read_reference_scan_leaf_rank3(tmp_path):
    from pbg_biomodels.reference_results import read_reference_scan_leaf
    h5 = tmp_path / "reports.h5"
    _write_scan_h5(h5, (3, 4, 5), ["Time", "A", "B"])  # 3 labels, 4 scan, 5 time
    leaf = read_reference_scan_leaf(h5, scan_values=[0.5, 1.5, 2.5, 3.5])
    assert leaf["scan"] == [0.5, 1.5, 2.5, 3.5]
    assert "Time" not in leaf                       # time row dropped
    assert leaf["A"] == pytest.approx([100.0, 101.0, 102.0, 103.0])
    assert leaf["B"] == pytest.approx([200.0, 201.0, 202.0, 203.0])


def test_read_reference_scan_leaf_rank4_flattens(tmp_path):
    from pbg_biomodels.reference_results import read_reference_scan_leaf
    h5 = tmp_path / "reports.h5"
    _write_scan_h5(h5, (2, 2, 1, 5), ["Time", "A"])  # matches observed 4-D shape
    leaf = read_reference_scan_leaf(h5, scan_values=[10.0, 20.0])
    assert leaf["scan"] == [10.0, 20.0]              # 2*1 scan dims flattened -> 2
    assert leaf["A"] == pytest.approx([100.0, 101.0])


def test_read_reference_scan_leaf_absent_on_utc_only(tmp_path):
    """A rank-2 (plain UTC) report yields no scan leaf."""
    import h5py
    import numpy as np
    from pbg_biomodels.reference_results import read_reference_scan_leaf
    h5 = tmp_path / "reports.h5"
    with h5py.File(h5, "w") as f:
        ds = f.create_group("doc.sedml").create_dataset(
            "report", data=np.zeros((2, 5)))
        ds.attrs["_type"] = "SedReport"
        ds.attrs["sedmlDataSetLabels"] = ["Time", "A"]
    assert read_reference_scan_leaf(h5) == {}
