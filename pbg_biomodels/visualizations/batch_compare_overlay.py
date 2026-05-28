"""BatchCompareOverlay — N-simulator + multi-sedml-doc summary-card grid.

Each biomodel gets a card colored by its worst-pair bucket (aggregated
across sedml docs); clicking the card reveals a tab strip with one tab
per sedml doc, and each tab renders a per-observable overlay across the
simulators that produced output. Steady-state observables render as a
small grouped bar chart of final values instead of a line.

The HTML is a self-contained fragment that includes Plotly inline.
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

_BUCKET_RANK = {"good": 0, "borderline": 1, "large": 2, "none": -1}


def _aggregate_card_bucket(per_doc_comparisons: Dict[str, Any]) -> Dict[str, Any]:
    """Pick the worst (largest-mean-nrmse) bucket across this biomodel's docs."""
    worst = None
    for cmp_dict in (per_doc_comparisons or {}).values():
        if not cmp_dict:
            continue
        if worst is None:
            worst = cmp_dict
            continue
        wr = _BUCKET_RANK.get(worst.get("bucket"), -1)
        cr = _BUCKET_RANK.get(cmp_dict.get("bucket"), -1)
        if cr > wr:
            worst = cmp_dict
    return worst or {"bucket": "none", "bucket_label": "No comparison",
                     "max_nrmse": None, "engines": []}


def _utc_overlay_figure(
    sim_results: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Per-observable small-multiples overlay across simulators."""
    species_order: List[str] = []
    seen: set = set()
    for sr in sim_results.values():
        for sp in (sr.get("observables") or {}).keys():
            if sp not in seen:
                seen.add(sp)
                species_order.append(sp)

    if not species_order:
        return {"data": [], "layout": {"title": "No observables"}}

    cols = 3
    rows = (len(species_order) + cols - 1) // cols
    traces: List[Dict[str, Any]] = []
    layout: Dict[str, Any] = {
        "grid":   {"rows": rows, "columns": cols, "pattern": "independent"},
        "height": 220 * rows + 100,
        "legend": {"orientation": "h", "y": 1.04, "x": 0},
        "margin": {"t": 60, "b": 40, "l": 60, "r": 20},
    }
    seen_legend: set = set()
    for i, sp in enumerate(species_order):
        idx = i + 1
        x_key = "xaxis" + ("" if idx == 1 else str(idx))
        y_key = "yaxis" + ("" if idx == 1 else str(idx))
        x_ref = "x" if idx == 1 else f"x{idx}"
        y_ref = "y" if idx == 1 else f"y{idx}"
        layout[y_key] = {"title": {"text": sp}}
        layout[x_key] = {"title": {"text": "time"}}
        for sim_name, sr in sim_results.items():
            obs = (sr.get("observables") or {})
            series = obs.get(sp)
            time = sr.get("time")
            if series is None or time is None:
                continue
            traces.append({
                "x": list(time), "y": list(series),
                "mode": "lines", "name": sim_name,
                "legendgroup": sim_name,
                "showlegend": sim_name not in seen_legend,
                "xaxis": x_ref, "yaxis": y_ref,
            })
            seen_legend.add(sim_name)
    return {"data": traces, "layout": layout}


def _ss_bar_figure(sim_results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Grouped bar chart of final steady-state values across simulators."""
    species: List[str] = []
    seen: set = set()
    for sr in sim_results.values():
        for sp in (sr.get("observables") or {}).keys():
            if sp not in seen:
                seen.add(sp)
                species.append(sp)
    if not species:
        return {"data": [], "layout": {"title": "No observables"}}
    traces = [
        {
            "type": "bar",
            "name": sim_name,
            "x":    species,
            "y":    [float((sr.get("observables") or {}).get(sp, 0.0)) for sp in species],
        }
        for sim_name, sr in sim_results.items()
    ]
    return {"data": traces, "layout": {"barmode": "group", "height": 360}}


def _card_html(bid: str, agg: Dict[str, Any]) -> str:
    bucket = agg.get("bucket") or "none"
    label = agg.get("bucket_label") or "No comparison"
    max_n = agg.get("max_nrmse")
    n_eng = len(agg.get("engines") or [])
    max_str = f"{max_n:.4g}" if isinstance(max_n, (int, float)) else "—"
    color = _BUCKET_COLOR.get(bucket, "#5d6573")
    return (
        f'<div class="biomodel-card" data-biomodel="{bid}" '
        f'style="border-left:6px solid {color};padding:10px 14px;'
        f'background:#fafbfc;font-family:-apple-system,sans-serif;'
        f'cursor:pointer;border-radius:4px;'
        f'display:flex;align-items:center;gap:12px;">'
        f'<span class="chevron" style="font-size:11px;color:#888;width:10px;'
        f'transition:transform 0.15s;display:inline-block;">▶</span>'
        f'<div style="flex:1;"><div style="font-weight:600;font-size:13px;">{bid}</div>'
        f'<div style="font-size:12px;color:#444;margin-top:2px;">{label} · '
        f'worst nRMSE {max_str} · {n_eng} engines</div></div></div>'
    )


def _detail_html(bid: str, doc_figs: Dict[str, Dict[str, Any]]) -> str:
    """Render the tab strip + plot containers for one biomodel's sedml docs."""
    if not doc_figs:
        body = '<div style="color:#888;padding:8px;">No data for this biomodel.</div>'
    else:
        tabs = "".join(
            f'<button class="batch-tab" data-bid="{bid}" data-doc="{doc}" '
            f'style="margin-right:4px;padding:4px 10px;font-size:12px;">{doc}</button>'
            for doc in doc_figs.keys()
        )
        panes = "".join(
            f'<div class="batch-pane" id="pane-{bid}-{doc}" '
            f'style="display:none;"><div id="plot-{bid}-{doc}"></div></div>'
            for doc in doc_figs.keys()
        )
        body = (
            f'<div class="batch-tab-strip" style="margin-bottom:8px;">{tabs}</div>'
            f'{panes}'
        )
        fig_blob = {doc: fig for doc, fig in doc_figs.items()}
        body += (
            "<script>"
            "window.__batchFigures = window.__batchFigures || {};"
            f'window.__batchFigures[{json.dumps(bid)}] = {json.dumps(fig_blob)};'
            "</script>"
        )
    return (
        f'<div id="detail-{bid}" class="biomodel-detail" '
        f'style="display:none;padding:8px 14px 14px 28px;'
        f'background:#fcfcfd;border-left:1px solid #e5e7eb;'
        f'border-radius:0 0 4px 4px;margin-top:-2px;">{body}</div>'
    )


_TOGGLE_JS = """
window.__batchFigures = window.__batchFigures || {};
window.__batchFigsPlotted = window.__batchFigsPlotted || {};
function _ensurePlot(bid, doc) {
  var key = bid + "::" + doc;
  if (window.__batchFigsPlotted[key]) return;
  var fig = (window.__batchFigures[bid] || {})[doc];
  if (!fig || !window.Plotly) return;
  window.Plotly.newPlot("plot-" + bid + "-" + doc, fig.data, fig.layout,
                        {responsive: true, displaylogo: false});
  window.__batchFigsPlotted[key] = true;
}
document.querySelectorAll('.biomodel-card').forEach(function(card) {
  card.addEventListener('click', function() {
    var bid = card.getAttribute('data-biomodel');
    var pane = document.getElementById('detail-' + bid);
    if (!pane) return;
    var isOpen = pane.style.display !== 'none';
    pane.style.display = isOpen ? 'none' : 'block';
    var chev = card.querySelector('.chevron');
    if (chev) chev.style.transform = isOpen ? 'rotate(0deg)' : 'rotate(90deg)';
    if (!isOpen) {
      var firstTab = pane.querySelector('.batch-tab');
      if (firstTab) firstTab.click();
    }
  });
});
document.querySelectorAll('.batch-tab').forEach(function(tab) {
  tab.addEventListener('click', function() {
    var bid = tab.getAttribute('data-bid');
    var doc = tab.getAttribute('data-doc');
    var detail = document.getElementById('detail-' + bid);
    if (!detail) return;
    detail.querySelectorAll('.batch-pane').forEach(function(p) {
      p.style.display = 'none';
    });
    var pane = document.getElementById('pane-' + bid + '-' + doc);
    if (pane) pane.style.display = 'block';
    _ensurePlot(bid, doc);
  });
});
"""


class BatchCompareOverlay(Visualization):
    """N-simulator + multi-sedml-doc card-grid overlay.

    Inputs:
        results: `map[bid, map[sim, map[sedml_doc, simulation_result]]]`.
        comparisons: `map[bid, map[sedml_doc, tree]]`.

    Output: a single `html` fragment.
    """

    config_schema = {
        "title":        {"_type": "string", "_default": ""},
        "biomodel_ids": {"_type": "list[string]", "_default": []},
    }

    def inputs(self) -> Dict[str, Any]:
        return {"results": "tree", "comparisons": "tree"}

    def update(self, state: Dict[str, Any]) -> Dict[str, str]:
        results = state.get("results") or {}
        comparisons = state.get("comparisons") or {}
        ids = list((self.config or {}).get("biomodel_ids") or []) or list(results.keys())

        if not ids or not results:
            return {"html":
                '<div style="padding:20px;color:#888;'
                'font-family:-apple-system,sans-serif;">'
                'No biomodels to compare.</div>'}

        # Build a per-bid index from results[sim][bid][doc].
        per_bid_doc_sim: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for sim_name, per_bid in results.items():
            for bid, per_doc in (per_bid or {}).items():
                for doc, sim_result in (per_doc or {}).items():
                    if not sim_result:
                        continue
                    per_bid_doc_sim.setdefault(bid, {}).setdefault(doc, {})
                    per_bid_doc_sim[bid][doc][sim_name] = sim_result

        rows: List[str] = []
        for bid in ids:
            doc_map = per_bid_doc_sim.get(bid) or {}
            doc_figs: Dict[str, Dict[str, Any]] = {}
            for doc, sim_results in doc_map.items():
                if not sim_results:
                    continue
                first_kind = next(iter(sim_results.values())).get("kind")
                if first_kind == "steady_state":
                    doc_figs[doc] = _ss_bar_figure(sim_results)
                else:
                    doc_figs[doc] = _utc_overlay_figure(sim_results)

            agg = _aggregate_card_bucket(comparisons.get(bid) or {})
            rows.append(_card_html(bid, agg))
            rows.append(_detail_html(bid, doc_figs))

        title = (self.config or {}).get("title", "")
        title_html = (
            f'<h3 style="margin:0 0 12px 0;font-family:-apple-system,sans-serif;">'
            f'{title}</h3>'
        ) if title else ''
        return {"html": (
            f'<div>{title_html}'
            f'<div class="biomodel-list" style="'
            f'display:flex;flex-direction:column;gap:4px;">'
            + "".join(rows) +
            '</div>'
            f'<script>{get_plotlyjs()}</script>'
            f'<script>{_TOGGLE_JS}</script>'
            '</div>'
        )}
