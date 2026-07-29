"""``ZarrExportStep`` — write the batch results to a single zarr artifact.

Wired at the end of the ``batch-compare-biomodels`` composite (after the
comparison Step), this consumes the nested ``results`` store
(``biomodel > sedml_job > simulator``), the ``comparisons``, and the
``diagnostics``, and writes one self-describing zarr in the
``biomodel / simulator / sedml_job`` hierarchy — including the folded-in
``reference:<engine>`` leaves. It emits the written path on ``zarr_path`` so a
consumer (or the emitter) can pick it up at the end of the run.

The heavy lifting lives in :func:`viva_biomodels.zarr_export.write_zarr`, shared
with the offline two-tier converter so both producers emit an identical layout.
"""
from __future__ import annotations

from typing import Any, ClassVar, Dict

from process_bigraph import Step


class ZarrExportStep(Step):
    """Translate the nested batch ``results`` store into a zarr artifact.

    Config:
        out_path: destination ``.zarr`` directory (default ``batch_results.zarr``).

    Inputs:
        results: ``biomodel > sedml_job > simulator > results`` (the nested
            store the runners + reference loader write).
        comparisons: ``biomodel > sedml_job -> compare rollup`` (stored as
            per-biomodel zarr group attrs).
        diagnostics: host/provenance/per-run timing (per-biomodel attrs).

    Outputs:
        zarr_path: absolute path of the written zarr store.
    """

    config_schema: ClassVar[Dict[str, Any]] = {
        "out_path": {"_type": "string", "_default": "batch_results.zarr"},
    }

    def inputs(self) -> Dict[str, str]:
        return {"results": "tree", "comparisons": "tree", "diagnostics": "tree"}

    def outputs(self) -> Dict[str, str]:
        return {"zarr_path": "string"}

    def update(self, state: Dict[str, Any]) -> Dict[str, Any]:
        from viva_biomodels.zarr_export import write_zarr

        results = state.get("results") or {}
        if not results:
            return {"zarr_path": ""}
        path = write_zarr(
            self.config.get("out_path") or "batch_results.zarr",
            results,
            comparisons=state.get("comparisons") or {},
            diagnostics=state.get("diagnostics") or {},
            meta={"source": "batch-compare-biomodels composite (ZarrExportStep)"},
        )
        return {"zarr_path": path}
