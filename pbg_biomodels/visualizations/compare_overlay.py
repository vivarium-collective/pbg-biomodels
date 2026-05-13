"""Overlay viz: two simulators' trajectories per species + match summary.

Direct ``Visualization`` subclass. Earlier this module used the
``@as_visualization`` decorator from ``pbg_superpowers.visualization``, but
that helper is branch-specific in the in-development pbg-superpowers tree
(present on release-v0.6.1, absent on main) — and the dashboard's
post-run viz collector (:func:`pbg_superpowers.visualization.render_results`)
is on the opposite branch. Subclassing directly works regardless and
satisfies both the Step contract and ``find_instance_paths``' isinstance
check used by ``render_results``.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from plotly.offline import get_plotlyjs

from pbg_superpowers.visualization import Visualization


_BUCKET_COLOR = {
    "good":       "#1b6e3c",
    "borderline": "#b8741a",
    "large":      "#b3261e",
    "none":       "#5d6573",
}


def _series_by_species(payload: Dict[str, Any]) -> Dict[str, List[float]]:
    cols = payload.get("columns", []) or []
    values = payload.get("values", []) or []
    out: Dict[str, List[float]] = {}
    for j, sp in enumerate(cols):
        out[sp] = [row[j] for row in values]
    return out


def _bucket_banner_html(comparison: Dict[str, Any]) -> str:
    bucket = (comparison or {}).get("bucket") or "none"
    label = (comparison or {}).get("bucket_label") or "No comparison"
    mean = (comparison or {}).get("mean_nrmse")
    n_shared = (comparison or {}).get("n_shared") or 0
    mean_str = f"{mean:.4g}" if isinstance(mean, (int, float)) else "—"
    color = _BUCKET_COLOR.get(bucket, "#5d6573")
    return (
        f'<div style="border-left:6px solid {color};padding:8px 14px;'
        f'background:#fafbfc;font-family:-apple-system,sans-serif;'
        f'margin-bottom:12px;">'
        f'<strong>{label}</strong> · mean nRMSE {mean_str} '
        f'across {n_shared} shared species'
        f'</div>'
    )


def _build_figure(
    a_series: Dict[str, List[float]],
    a_time: List[float],
    a_name: str,
    b_series: Dict[str, List[float]],
    b_time: List[float],
    b_name: str,
) -> Dict[str, Any]:
    species = []
    seen = set()
    for sp in list(a_series.keys()) + list(b_series.keys()):
        if sp not in seen:
            seen.add(sp)
            species.append(sp)

    if not species:
        return {"data": [], "layout": {"title": "No shared species"}}

    cols = 3
    rows = (len(species) + cols - 1) // cols

    traces: List[Dict[str, Any]] = []
    layout: Dict[str, Any] = {
        "grid": {"rows": rows, "columns": cols, "pattern": "independent"},
        "height": 220 * rows + 100,
        "legend": {"orientation": "h", "y": 1.04, "x": 0},
        "margin": {"t": 60, "b": 40, "l": 60, "r": 20},
    }
    seen_legend: set = set()

    for i, sp in enumerate(species):
        idx = i + 1
        x_key = "xaxis" + ("" if idx == 1 else str(idx))
        y_key = "yaxis" + ("" if idx == 1 else str(idx))
        x_ref = "x" if idx == 1 else f"x{idx}"
        y_ref = "y" if idx == 1 else f"y{idx}"
        layout[y_key] = {"title": {"text": sp}}
        layout[x_key] = {"title": {"text": "time"}}

        for name, series, t in (
            (a_name, a_series.get(sp), a_time),
            (b_name, b_series.get(sp), b_time),
        ):
            if series is None or t is None:
                continue
            traces.append({
                "x": t,
                "y": series,
                "mode": "lines",
                "name": name,
                "legendgroup": name,
                "showlegend": name not in seen_legend,
                "xaxis": x_ref,
                "yaxis": y_ref,
            })
            seen_legend.add(name)

    return {"data": traces, "layout": layout}


class CompareOverlay(Visualization):
    """Plotly small-multiples overlay of two simulator trajectories.

    Inputs:
        engine_a_result: ``numeric_result`` from the first simulator.
        engine_b_result: ``numeric_result`` from the second simulator.
        comparison:      summary dict from :class:`SimulatorComparisonStep`.

    Output: an HTML fragment with embedded Plotly JS plus a bucket-colored
    banner showing the mean nRMSE across shared species.
    """

    config_schema = {
        "title": {"_type": "string", "_default": ""},
    }

    def inputs(self) -> Dict[str, Any]:
        return {
            "engine_a_result": "numeric_result",
            "engine_b_result": "numeric_result",
            "comparison": {
                "n_shared":         "integer",
                "rmse_by_species":  "map[float]",
                "nrmse_by_species": "map[float]",
                "mean_nrmse":       "maybe[float]",
                "bucket":           "string",
                "bucket_label":     "string",
            },
        }

    def update(self, state: Dict[str, Any]) -> Dict[str, str]:
        a = state.get("engine_a_result") or {}
        b = state.get("engine_b_result") or {}
        comparison = state.get("comparison") or {}

        a_series = _series_by_species(a)
        b_series = _series_by_species(b)
        a_time = a.get("time") or []
        b_time = b.get("time") or []

        fig = _build_figure(
            a_series, a_time, "engine_a",
            b_series, b_time, "engine_b",
        )

        banner = _bucket_banner_html(comparison)
        fig_json = json.dumps(fig).replace("</", "<\\/")
        html = (
            f'<div>{banner}'
            f'<div id="overlay-plot"></div>'
            f'<script>{get_plotlyjs()}</script>'
            f'<script>'
            f'(function() {{'
            f'  var d = {fig_json};'
            f'  Plotly.newPlot("overlay-plot", d.data, d.layout, '
            f'    {{responsive: true, displaylogo: false}});'
            f'}})();'
            f'</script>'
            f'</div>'
        )
        return {"html": html}
