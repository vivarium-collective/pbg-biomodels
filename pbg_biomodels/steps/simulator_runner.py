"""SimulatorRunnerStep — runs every SED-ML job of every biomodel under one simulator.

The runner reads a `map[biomodel_id, biomodel_jobs]` input (the `models`
store, populated upstream by per-biomodel `LoadBiomodelStep` instances)
and writes a `map[bid, map[sedml_doc_name, simulation_result]]` slice
keyed by the simulator this runner is configured for. One runner instance
per simulator replaces the (simulator x biomodel) Step explosion of the
legacy compare-biomodel composite.

Each job is dispatched in-process, sequentially. A job exception is caught
and recorded as `{"kind", "time": None, "observables": {}, "error": "..."}`
under the job's name; the runner's other jobs continue.
"""
from __future__ import annotations

from typing import Any, ClassVar, Dict

from process_bigraph import Step

from pbg_biomodels.simulators import ALL_SIMULATORS


# ---------------------------------------------------------------------------
# Adapter class lookup — kept as module-level functions so tests can
# monkeypatch them without standing up the real upstream simulator stack.
# ---------------------------------------------------------------------------


def _UTC_CLASS_FOR(simulator_name: str):
    """Return the UTC adapter class for the given simulator."""
    from pbg_biomodels.steps.simulators import (
        BiomodelsCopasiStep,
        BiomodelsSimbioStep,
        BiomodelsTelluriumStep,
    )
    return {
        "copasi":    BiomodelsCopasiStep,
        "tellurium": BiomodelsTelluriumStep,
        "simbio":    BiomodelsSimbioStep,
    }[simulator_name]


def _SS_CLASS_FOR(simulator_name: str):
    """Return the SteadyState adapter class for the given simulator."""
    from pbg_biomodels.steps.simulators import (
        BiomodelsCopasiSteadyStateStep,
        BiomodelsSimbioSteadyStateStep,
        BiomodelsTelluriumSteadyStateStep,
    )
    return {
        "copasi":    BiomodelsCopasiSteadyStateStep,
        "tellurium": BiomodelsTelluriumSteadyStateStep,
        "simbio":    BiomodelsSimbioSteadyStateStep,
    }[simulator_name]


def _utc_to_simulation_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Reshape `{time, columns, values}` -> simulation_result tagged-union."""
    result = (payload or {}).get("result") or {}
    cols = result.get("columns") or []
    values = result.get("values") or []
    observables: Dict[str, list] = {sp: [] for sp in cols}
    for row in values:
        for j, sp in enumerate(cols):
            observables[sp].append(float(row[j]))
    return {
        "kind":        "utc",
        "time":        list(result.get("time") or []),
        "observables": observables,
    }


def _ss_to_simulation_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Pass through the adapter's already-shaped simulation_result."""
    result = (payload or {}).get("result") or {}
    return {
        "kind":        "steady_state",
        "time":        None,
        "observables": dict(result.get("observables") or {}),
    }


class SimulatorRunnerStep(Step):
    """Run every SED-ML job of every biomodel under one configured simulator.

    Config:
        simulator_name: one of `ALL_SIMULATORS` (`copasi`, `tellurium`,
            `simbio`).

    Inputs:
        models: `map[biomodel_id, biomodel_jobs]` — each entry has
            `sbml_path` + `sedml_jobs` (the LoadBiomodelStep output).

    Outputs:
        results: `map[biomodel_id, map[sedml_doc_name, simulation_result]]`
            — this simulator's slice of the full results tree.
    """

    config_schema: ClassVar[Dict[str, Any]] = {
        "simulator_name": {"_type": "string", "_default": "copasi"},
    }

    def inputs(self) -> Dict[str, str]:
        return {"models": "map[biomodel_jobs]"}

    def outputs(self) -> Dict[str, str]:
        # `tree` (not `sim_results_per_biomodel = map[map[simulation_result]]`)
        # because the runner emits NEW keys at both nesting levels — bid +
        # sedml_doc are not known to the upstream schema. Map's apply
        # semantics skip update keys that don't already exist in state
        # (no implicit `_add`); tree's apply inserts them. The shape of
        # the leaves is still simulation_result; only the container
        # apply-rules change.
        return {"results": "tree"}

    def update(self, state: Dict[str, Any]) -> Dict[str, Any]:
        name = self.config["simulator_name"]
        if name not in ALL_SIMULATORS:
            raise ValueError(
                f"SimulatorRunnerStep: unknown simulator {name!r}; "
                f"known: {ALL_SIMULATORS}"
            )

        utc_cls = _UTC_CLASS_FOR(name)
        ss_cls = _SS_CLASS_FOR(name)

        out: Dict[str, Dict[str, Any]] = {}
        for bid, model in (state.get("models") or {}).items():
            out[bid] = {}
            sbml_path = (model or {}).get("sbml_path") or ""
            for job in (model or {}).get("sedml_jobs") or []:
                job_name = job.get("name") or "sim"
                kind = job.get("kind")
                try:
                    if kind == "utc":
                        inner = utc_cls(core=getattr(self, "core", None))
                        payload = inner.update({
                            "model_source": sbml_path,
                            "time":         float(job.get("time") or 0.0),
                            "n_points":     int(job.get("n_points") or 2),
                        })
                        out[bid][job_name] = _utc_to_simulation_result(payload)
                    elif kind == "steady_state":
                        inner = ss_cls(core=getattr(self, "core", None))
                        payload = inner.update({"model_source": sbml_path})
                        out[bid][job_name] = _ss_to_simulation_result(payload)
                    else:
                        out[bid][job_name] = {
                            "kind":        str(kind),
                            "time":        None,
                            "observables": {},
                            "error":       f"unknown job kind {kind!r}",
                        }
                except Exception as exc:
                    out[bid][job_name] = {
                        "kind":        kind or "unknown",
                        "time":        None,
                        "observables": {},
                        "error":       f"{type(exc).__name__}: {exc}",
                    }
        return {"results": out}
