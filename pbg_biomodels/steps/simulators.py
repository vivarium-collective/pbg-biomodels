"""Thin runtime-input wrappers around pbg-copasi / pbg-tellurium UTC Steps.

Adapter Steps for the compare-biomodel composite: take ``model_source``,
``time``, ``n_points`` as runtime inputs (so LoadBiomodelStep can feed
them dynamically) and emit the canonical ``numeric_result`` shape on the
``result`` output port. Delegates the actual simulation to the canonical
classes in pbg-tellurium and pbg-copasi.
"""
from __future__ import annotations

from typing import Any, ClassVar, Dict

from process_bigraph import Step

from pbg_copasi.processes import CopasiUTCStep
from pbg_tellurium.processes import TelluriumUTCStep


_UTC_INPUTS: Dict[str, str] = {
    "model_source": "string",
    "time":         "float",
    "n_points":     "integer",
}


def _validate_n_points(n: Any, where: str) -> int:
    try:
        n = int(n)
    except (TypeError, ValueError):
        raise ValueError(f"{where}: n_points must be an integer >= 2, got {n!r}")
    if n < 2:
        raise ValueError(f"{where}: n_points must be >= 2, got {n}")
    return n


class BiomodelsCopasiStep(Step):
    """Adapter: runtime ``model_source`` → ``pbg_copasi.CopasiUTCStep``.

    CopasiUTCStep.config_schema uses keys: model_source, time, n_points.
    Its update() already returns {'result': {'time', 'columns', 'values'}},
    so no reshape is needed — pass through directly.
    """

    config_schema: ClassVar[Dict[str, Any]] = {}

    def inputs(self) -> Dict[str, str]:
        return dict(_UTC_INPUTS)

    def outputs(self) -> Dict[str, str]:
        return {"result": "numeric_result"}

    def update(self, state: Dict[str, Any]) -> Dict[str, Any]:
        n_points = _validate_n_points(state["n_points"], "BiomodelsCopasiStep")
        inner = CopasiUTCStep(
            config={
                "model_source": state["model_source"],
                "time":         float(state["time"]),
                "n_points":     n_points,
            },
            core=self.core,
        )
        out = inner.update({})
        return {"result": out["result"]}


class BiomodelsTelluriumStep(Step):
    """Adapter: runtime ``model_source`` → ``pbg_tellurium.TelluriumUTCStep``.

    TelluriumUTCStep.config_schema uses keys: model (the SBML/antimony
    source string), model_format, start_time, end_time, n_points.
    Its update() returns {'time_series': list, 'species_trajectories': map[list]};
    this wrapper reshapes to the canonical {'result': {'time', 'columns', 'values'}}.
    """

    config_schema: ClassVar[Dict[str, Any]] = {}

    def inputs(self) -> Dict[str, str]:
        return dict(_UTC_INPUTS)

    def outputs(self) -> Dict[str, str]:
        return {"result": "numeric_result"}

    def update(self, state: Dict[str, Any]) -> Dict[str, Any]:
        n_points = _validate_n_points(state["n_points"], "BiomodelsTelluriumStep")
        inner = TelluriumUTCStep(
            config={
                "model":        state["model_source"],
                "model_format": "sbml",
                "start_time":   0.0,
                "end_time":     float(state["time"]),
                "n_points":     n_points,
            },
            core=self.core,
        )
        out = inner.update({})
        # Reshape from {time_series, species_trajectories} → {result: {time, columns, values}}
        time_list = list(out["time_series"])
        trajectories = out["species_trajectories"]
        columns = list(trajectories.keys())
        n_rows = len(time_list)
        values = [
            [float(trajectories[c][r]) for c in columns]
            for r in range(n_rows)
        ]
        return {
            "result": {
                "time":    time_list,
                "columns": columns,
                "values":  values,
            }
        }
