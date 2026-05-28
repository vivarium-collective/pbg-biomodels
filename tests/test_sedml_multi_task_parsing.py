"""`extract_all_simulations` returns every UTC + SteadyState task in a
SED-ML document, in declaration order, with `kind` tagged so downstream
dispatch can branch.
"""
from pathlib import Path
import textwrap

import libsedml
import pytest

from pbg_biomodels.run_biomodels import extract_all_simulations, read_sedml_doc


def _write(tmp_path, body) -> str:
    p = tmp_path / "sample.sedml"
    p.write_text(textwrap.dedent(body))
    return str(p)


def test_single_utc_task_yields_one_job(tmp_path):
    path = _write(tmp_path, """\
    <?xml version="1.0" encoding="UTF-8"?>
    <sedML xmlns="http://sed-ml.org/sed-ml/level1/version3" level="1" version="3">
      <listOfSimulations>
        <uniformTimeCourse id="sim1" initialTime="0" outputStartTime="0"
                           outputEndTime="10" numberOfPoints="100"/>
      </listOfSimulations>
    </sedML>
    """)
    jobs = extract_all_simulations(read_sedml_doc(path))
    assert len(jobs) == 1
    assert jobs[0]["kind"] == "utc"
    assert jobs[0]["name"] == "sim1"
    assert jobs[0]["time"] == pytest.approx(10.0)
    assert jobs[0]["n_points"] == 100


def test_mixed_utc_and_steady_state(tmp_path):
    path = _write(tmp_path, """\
    <?xml version="1.0" encoding="UTF-8"?>
    <sedML xmlns="http://sed-ml.org/sed-ml/level1/version3" level="1" version="3">
      <listOfSimulations>
        <uniformTimeCourse id="utc_short" initialTime="0" outputStartTime="0"
                           outputEndTime="1" numberOfPoints="10"/>
        <steadyState id="ss"/>
        <uniformTimeCourse id="utc_long" initialTime="0" outputStartTime="0"
                           outputEndTime="100" numberOfPoints="500"/>
      </listOfSimulations>
    </sedML>
    """)
    jobs = extract_all_simulations(read_sedml_doc(path))
    kinds = [j["kind"] for j in jobs]
    names = [j["name"] for j in jobs]
    assert kinds == ["utc", "steady_state", "utc"]
    assert names == ["utc_short", "ss", "utc_long"]
    assert jobs[1]["time"] is None
    assert jobs[1]["n_points"] is None


def test_no_simulations_returns_empty_list(tmp_path):
    path = _write(tmp_path, """\
    <?xml version="1.0" encoding="UTF-8"?>
    <sedML xmlns="http://sed-ml.org/sed-ml/level1/version3" level="1" version="3">
      <listOfSimulations/>
    </sedML>
    """)
    assert extract_all_simulations(read_sedml_doc(path)) == []
