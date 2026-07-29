"""Tests for the standalone CLI surface: registry, comparison, references,
both composite builders, the report, and the CLI argument plumbing.

Network-free: the pluggable-process composite is exercised with pbg-copasi's
bundled SBML; comparison/report use synthetic numeric_result payloads.
"""
from importlib.resources import files

import pytest
from process_bigraph import Composite, gather_emitter_results

from viva_biomodels import register_types
from viva_biomodels.cli import _parse_references, build_parser
from viva_biomodels.comparison import compare_n_engines
from viva_biomodels.composites.biomodel_process import build_biomodel_process_document
from viva_biomodels.composites.compare_simulators import build_compare_document
from viva_biomodels.core import build_core
from viva_biomodels.report import build_comparison_report
from viva_biomodels.simulators import (
    ALL_SIMULATORS,
    process_config,
    resolve_simulators,
)
from viva_biomodels.steps.reference_data import load_reference_csv


def _sbml() -> str:
    return str(files("pbg_copasi.composites") / "repressilator.xml")


def _nr(scale=1.0):
    return {
        "time": [0, 1, 2, 3],
        "columns": ["S1", "S2"],
        "values": [[1 * scale, 2], [1.1 * scale, 2.1],
                   [1.2 * scale, 2.2], [1.3 * scale, 2.3]],
    }


# --- registry ---------------------------------------------------------------

def test_resolve_simulators_all_and_subset():
    assert resolve_simulators("all") == ALL_SIMULATORS
    assert resolve_simulators("copasi,simbio") == ["copasi", "simbio"]
    assert resolve_simulators(["tellurium"]) == ["tellurium"]


def test_resolve_simulators_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown simulator"):
        resolve_simulators("not_a_sim")


def test_process_config_differs_per_simulator():
    assert process_config("copasi", "/m.xml")["model_source"] == "/m.xml"
    assert process_config("tellurium", "/m.xml")["model_file"] == "/m.xml"
    assert process_config("simbio", "/m.xml")["model_format"] == "sbml"


# --- N-way comparison -------------------------------------------------------

def test_compare_n_engines_all_pairs():
    res = compare_n_engines({"a": _nr(1.0), "b": _nr(1.0), "c": _nr(3.0)})
    assert res["engines"] == ["a", "b", "c"]
    assert set(res["pairs"]) == {"a__b", "a__c", "b__c"}
    # a vs b identical -> 0; both differ a lot from c -> c is in the worst pair
    assert res["matrix"]["a"]["b"] == 0.0
    assert "c" in res["worst_pair"]
    assert res["matrix"]["a"]["a"] is None


def test_compare_n_engines_handles_missing():
    res = compare_n_engines({"a": _nr(), "b": {}})  # b empty
    assert res["engines"] == ["a"]
    assert res["pairs"] == {}
    assert res["bucket"] == "none"


# --- reference CSV ----------------------------------------------------------

def test_load_reference_csv(tmp_path):
    p = tmp_path / "ref.csv"
    p.write_text("time,S1,S2\n0,1,2\n1,1.5,2.5\n")
    r = load_reference_csv(str(p))
    assert r["columns"] == ["S1", "S2"]
    assert r["time"] == [0.0, 1.0]
    assert r["values"][1] == [1.5, 2.5]


def test_parse_references():
    refs = _parse_references([
        "BIOMD1=a.csv",
        "BIOMD2:experiment=b.csv",
    ])
    assert refs["BIOMD1"] == {"reference": "a.csv"}
    assert refs["BIOMD2"] == {"experiment": "b.csv"}


def test_parse_references_rejects_bad():
    with pytest.raises(SystemExit):
        _parse_references(["no-equals-sign"])


# --- comparison composite document ------------------------------------------

def test_compare_document_structure_with_references():
    doc = build_compare_document(
        ["BIOMD0000000001"],
        simulators="copasi,simbio",
        references={"BIOMD0000000001": {"experiment": "/x.csv"}},
    )
    st = doc["state"]
    bid = "BIOMD0000000001"
    for key in (f"load_{bid}", f"copasi_step_{bid}", f"simbio_step_{bid}",
                f"ref_experiment_step_{bid}", f"compare_{bid}", "emitter"):
        assert key in st
    cmp = st[f"compare_{bid}"]
    assert cmp["config"]["engine_names"] == ["copasi", "simbio", "experiment"]
    assert cmp["inputs"]["experiment"] == [f"experiment_{bid}"]
    assert doc["run_steps_on_init"] is True


# --- single pluggable-process composite (runs offline) ----------------------

@pytest.mark.parametrize("simulator", ALL_SIMULATORS)
def test_biomodel_process_runs(simulator):
    doc = build_biomodel_process_document(
        "TEST", simulator, sbml_path=_sbml(), interval=5.0
    )
    composite = Composite(doc, core=register_types(build_core()))
    composite.run(15.0)
    rows = gather_emitter_results(composite).get(("emitter",), [])
    assert rows, "no emitter output"
    assert len(rows[-1]["species"]) > 0


def test_biomodel_process_rejects_multiple_simulators():
    with pytest.raises(ValueError):
        build_biomodel_process_document("TEST", "copasi,simbio", sbml_path=_sbml())


# --- report -----------------------------------------------------------------

def test_build_comparison_report(tmp_path):
    engines = {"copasi": _nr(1.0), "tellurium": _nr(1.02), "experiment": _nr(1.01)}
    results = {
        "BIOMD0000000001": {"engines": engines, "comparison": compare_n_engines(engines)},
    }
    out = build_comparison_report(results, str(tmp_path / "report.html"))
    html = out.read_text(encoding="utf-8")
    assert "BIOMD0000000001" in html
    assert "All-pairs nRMSE" in html
    assert "single-BIOMD0000000001-experiment" in html  # per-engine plot
    assert "Plotly.newPlot" in html


# --- CLI plumbing -----------------------------------------------------------

def test_cli_parser_compare_and_process():
    parser = build_parser()
    a = parser.parse_args(["compare", "BIOMD1", "BIOMD2", "--simulators", "simbio"])
    assert a.command == "compare" and a.biomodels == ["BIOMD1", "BIOMD2"]
    assert a.simulators == "simbio"
    b = parser.parse_args(["process", "BIOMD1", "--simulator", "copasi", "--run", "5"])
    assert b.command == "process" and b.biomodel == "BIOMD1" and b.run == 5
