"""``SimulatorComparisonStep`` — compare two simulator trajectories at runtime.

Inputs are two ``numeric_result`` payloads (the shape emitted by the COPASI
and Tellurium UTC steps in ``pbsim_common``):

    {"time": list[float], "columns": list[str], "values": list[list[float]]}

The Step delegates to ``pbg_biomodels.comparison.compare_two_engines``
so the math is shared with the post-hoc HTML report builder in
``analysis.py``. Output ``comparison`` is a free-form dict containing per-
species RMSE, normalized RMSE, mean nRMSE, and a coarse quality bucket.
"""
from __future__ import annotations

from typing import Any, ClassVar, Dict

from process_bigraph import Step

from pbg_biomodels.comparison import compare_n_engines, compare_two_engines


class SimulatorComparisonStep(Step):
    """Compare two simulator trajectories species-by-species.

    Configure with the engine names you want labelled in the output dict.
    Defaults match the canonical pair used by the bundle's regression flow.
    """

    config_schema = {
        "engine_a_name": {"_type": "string", "_default": "copasi"},
        "engine_b_name": {"_type": "string", "_default": "tellurium"},
    }

    def inputs(self) -> Dict[str, str]:
        return {
            "engine_a_result": "numeric_result",
            "engine_b_result": "numeric_result",
        }

    def outputs(self) -> Dict[str, Any]:
        # Concrete struct shape matches the dict returned by
        # `pbg_biomodels.comparison.compare_two_engines`. Declared
        # inline (rather than registered as a named type) so the bundle has
        # no module-init order requirement on workspace `register_types`.
        return {
            "comparison": {
                "n_shared":         "integer",
                "rmse_by_species":  "map[float]",
                "nrmse_by_species": "map[float]",
                "mean_nrmse":       "maybe[float]",
                "bucket":           "string",
                "bucket_label":     "string",
            }
        }

    def update(self, state: Dict[str, Any]) -> Dict[str, Any]:
        summary = compare_two_engines(
            engine_a=state.get("engine_a_result"),
            engine_b=state.get("engine_b_result"),
            name_a=self.config["engine_a_name"],
            name_b=self.config["engine_b_name"],
        )
        return {"comparison": summary}


class MultiSimulatorComparisonStep(Step):
    """All-pairs comparison across N named engines (simulators + references).

    The engine names are declared in ``config['engine_names']``; this Step
    exposes one ``numeric_result`` input port per engine (named exactly after
    the engine) and emits the :func:`compare_n_engines` result — an all-pairs
    nRMSE matrix plus a worst-pair bucket — on the ``comparison`` port.

    Generalizes :class:`SimulatorComparisonStep` (which is the pairwise case).
    """

    config_schema = {
        "engine_names": {"_type": "list[string]", "_default": []},
    }

    def inputs(self) -> Dict[str, str]:
        return {name: "numeric_result" for name in self.config["engine_names"]}

    def outputs(self) -> Dict[str, str]:
        # Free-form nested matrix; captured downstream as a tree/node.
        return {"comparison": "tree"}

    def update(self, state: Dict[str, Any]) -> Dict[str, Any]:
        engines = {name: (state or {}).get(name) for name in self.config["engine_names"]}
        return {"comparison": compare_n_engines(engines)}


class BatchCompareStep(Step):
    """All-pairs nRMSE across simulators per (biomodel_id, sedml_doc).

    Inputs:
        results: `map[bid, map[sedml_job, map[sim, results]]]` — the nested
            store the runners write, with the simulator as the innermost key
            and each leaf a flat `map[observable -> timeseries]`.

    Outputs:
        comparisons: `map[bid, map[sedml_job, tree]]` — each leaf is the
            `compare_n_engines` (UTC) or `compare_n_engines_steady_state`
            (SS) return shape.

    A `(bid, sedml_job)` whose simulators produced both UTC and SS leaves
    is treated as a SED-ML pathology: a warning is emitted and the leaf is
    the `"none"` bucket with empty engines.
    """

    config_schema: ClassVar[Dict[str, Any]] = {}

    def inputs(self) -> Dict[str, str]:
        return {"results": "tree"}

    def outputs(self) -> Dict[str, str]:
        return {"comparisons": "tree"}

    def update(self, state: Dict[str, Any]) -> Dict[str, Any]:
        from pbg_biomodels.comparison import (
            bucket_for,
            compare_n_engines,
            compare_n_engines_steady_state,
        )
        from pbg_biomodels import result_leaf
        import warnings

        results = state.get("results") or {}

        out: Dict[str, Dict[str, Any]] = {}
        # results is already keyed bid > job > sim; walk it directly.
        for bid, doc_map in results.items():
            out[bid] = {}
            for doc_name, sim_results_map in (doc_map or {}).items():
                utc_engines: Dict[str, Dict[str, Any]] = {}
                ss_engines: Dict[str, Dict[str, float]] = {}
                for sim_name, leaf in (sim_results_map or {}).items():
                    if not leaf:
                        continue  # failed/empty job — no engine slot
                    # UTC and parameter-scan leaves both carry an ordered axis
                    # (time / scan) and are scored by the same series metric.
                    if result_leaf.is_utc(leaf) or result_leaf.is_scan(leaf):
                        utc_engines[sim_name] = result_leaf.to_numeric_result(leaf)
                    else:
                        ss_engines[sim_name] = result_leaf.steady_state_scalars(leaf)

                if utc_engines and ss_engines:
                    warnings.warn(
                        f"BatchCompareStep: {bid!r}/{doc_name!r} has mixed kinds "
                        f"across simulators; skipping",
                        stacklevel=2,
                    )
                    bucket_id, bucket_label = bucket_for(None)
                    out[bid][doc_name] = {
                        "engines":      [],
                        "pairs":        {},
                        "matrix":       {},
                        "max_nrmse":    None,
                        "worst_pair":   None,
                        "bucket":       bucket_id,
                        "bucket_label": bucket_label,
                    }
                elif utc_engines:
                    out[bid][doc_name] = compare_n_engines(utc_engines)
                elif ss_engines:
                    out[bid][doc_name] = compare_n_engines_steady_state(ss_engines)
                else:
                    bucket_id, bucket_label = bucket_for(None)
                    out[bid][doc_name] = {
                        "engines":      [],
                        "pairs":        {},
                        "matrix":       {},
                        "max_nrmse":    None,
                        "worst_pair":   None,
                        "bucket":       bucket_id,
                        "bucket_label": bucket_label,
                    }

        return {"comparisons": out}
