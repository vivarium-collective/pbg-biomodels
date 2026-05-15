"""Multi-biomodel comparison viz: a grid of bucket-colored summary cards,
each expandable to that biomodel's species small-multiples overlay.

Direct ``Visualization`` subclass (the ``@as_visualization`` decorator helper
is branch-dependent in pbg-superpowers; subclassing directly avoids the
coupling). The single ``html`` output is a self-contained fragment that
includes Plotly + a click-to-toggle handler.

Input shape (produced by ``compare-biomodel`` generator's ``per_biomodel``
sub-tree):

    {
      "<biomodel_id>": {
        "copasi":     {time, columns, values},
        "tellurium":  {time, columns, values},
        "comparison": {n_shared, mean_nrmse, bucket, bucket_label, ...},
      },
      ...
    }
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


def _build_figure(
    a_series: Dict[str, List[float]],
    a_time: List[float],
    a_name: str,
    b_series: Dict[str, List[float]],
    b_time: List[float],
    b_name: str,
    a_color: str = "#1f77b4",  # Plotly default blue
    b_color: str = "#ff7f0e",  # Plotly default orange
) -> Dict[str, Any]:
    species: List[str] = []
    seen: set = set()
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
        for name, series, t, color in (
            (a_name, a_series.get(sp), a_time, a_color),
            (b_name, b_series.get(sp), b_time, b_color),
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
                "line": {"color": color},
            })
            seen_legend.add(name)

    return {"data": traces, "layout": layout}


def _card_html(bid: str, comparison: Dict[str, Any]) -> str:
    bucket = (comparison or {}).get("bucket") or "none"
    label = (comparison or {}).get("bucket_label") or "No comparison"
    mean = (comparison or {}).get("mean_nrmse")
    n_shared = (comparison or {}).get("n_shared") or 0
    mean_str = f"{mean:.4g}" if isinstance(mean, (int, float)) else "—"
    color = _BUCKET_COLOR.get(bucket, "#5d6573")
    return (
        f'<div class="biomodel-card" data-biomodel="{bid}" '
        f'style="border-left:6px solid {color};padding:10px 14px;'
        f'background:#fafbfc;font-family:-apple-system,sans-serif;'
        f'cursor:pointer;border-radius:4px;'
        f'display:flex;align-items:center;gap:12px;'
        f'transition:background 0.15s;"'
        f' onmouseover="this.style.background=\'#f0f3f7\'"'
        f' onmouseout="this.style.background=\'#fafbfc\'">'
        f'<span class="chevron" style="font-size:11px;color:#888;width:10px;'
        f'transition:transform 0.15s;display:inline-block;">▶</span>'
        f'<div style="flex:1;">'
        f'<div style="font-weight:600;font-size:13px;">{bid}</div>'
        f'<div style="font-size:12px;color:#444;margin-top:2px;">{label} · '
        f'mean nRMSE {mean_str} · {n_shared} shared species</div>'
        f'</div>'
        f'</div>'
    )


def _detail_html(bid: str, fig: Dict[str, Any]) -> str:
    fig_json = json.dumps(fig).replace("</", "<\\/")
    # Don't call Plotly.newPlot here — the pane starts display:none, so Plotly
    # can't measure the container and the plot renders at zero size. We stash
    # the figure in a global keyed by biomodel id; the toggle JS plots lazily
    # on first expand, when the container has its real dimensions.
    return (
        f'<div id="detail-{bid}" class="biomodel-detail" '
        f'style="display:none;padding:8px 14px 14px 28px;'
        f'background:#fcfcfd;border-left:1px solid #e5e7eb;'
        f'border-radius:0 0 4px 4px;margin-top:-2px;">'
        f'<div id="plot-{bid}"></div>'
        f'<script>'
        f'window.__compareFigures = window.__compareFigures || {{}};'
        f'window.__compareFigures["{bid}"] = {fig_json};'
        f'</script>'
        f'</div>'
    )


_TOGGLE_JS = """
window.__compareFigures = window.__compareFigures || {};
window.__compareFigsPlotted = window.__compareFigsPlotted || {};
document.querySelectorAll('.biomodel-card').forEach(function(card) {
  card.addEventListener('click', function() {
    var bid = card.getAttribute('data-biomodel');
    var pane = document.getElementById('detail-' + bid);
    if (!pane) return;
    var isOpen = pane.style.display !== 'none';
    pane.style.display = isOpen ? 'none' : 'block';
    var chev = card.querySelector('.chevron');
    if (chev) chev.style.transform = isOpen ? 'rotate(0deg)' : 'rotate(90deg)';
    // Lazy-plot on first expand: Plotly needs a visible container to size to.
    if (!isOpen && !window.__compareFigsPlotted[bid]) {
      var fig = window.__compareFigures[bid];
      if (fig && window.Plotly) {
        Plotly.newPlot('plot-' + bid, fig.data, fig.layout,
                       {responsive: true, displaylogo: false});
        window.__compareFigsPlotted[bid] = true;
      }
    }
  });
});
"""


class CompareOverlay(Visualization):
    """Summary-card grid + per-biomodel expandable species small-multiples.

    Inputs:
        per_biomodel: map of ``{<biomodel_id>: branch}``; each branch carries
            ``copasi`` / ``tellurium`` (``numeric_result``) and ``comparison``.

    Output: a self-contained HTML fragment.
    """

    config_schema = {
        "title":        {"_type": "string", "_default": ""},
        "biomodel_ids": {"_type": "list[string]", "_default": []},
    }

    def inputs(self) -> Dict[str, Any]:
        """Dynamic input ports — one numeric_result per engine per biomodel,
        plus one comparison record per biomodel. Driven by ``config.biomodel_ids``
        so the same class works for any N.

        comparison_<bid> is declared as a concrete record (not "any") because
        bigraph attaches a `_link_path` to the subschema at every wire target;
        that only works on a dict-shaped subschema, not a bare type string.
        """
        ids = (self.config or {}).get("biomodel_ids") or []
        comparison_shape: Dict[str, Any] = {
            "n_shared":         "integer",
            "rmse_by_species":  "map[float]",
            "nrmse_by_species": "map[float]",
            "mean_nrmse":       "maybe[float]",
            "bucket":           "string",
            "bucket_label":     "string",
        }
        decl: Dict[str, Any] = {}
        for bid in ids:
            decl[f"copasi_{bid}"]     = "numeric_result"
            decl[f"tellurium_{bid}"]  = "numeric_result"
            decl[f"comparison_{bid}"] = dict(comparison_shape)
        return decl

    def update(self, state: Dict[str, Any]) -> Dict[str, str]:
        ids = (self.config or {}).get("biomodel_ids") or []
        # Reassemble a per_biomodel view from the flat input ports.
        per: Dict[str, Dict[str, Any]] = {}
        for bid in ids:
            per[bid] = {
                "copasi":     state.get(f"copasi_{bid}")     or {},
                "tellurium":  state.get(f"tellurium_{bid}")  or {},
                "comparison": state.get(f"comparison_{bid}") or {},
            }
        if not per:
            return {"html":
                '<div style="padding:20px;color:#888;font-family:-apple-system,sans-serif;">'
                'No biomodels to compare.</div>'}

        # Interleave: each card is immediately followed by its detail pane so
        # the click-revealed plot lands directly under the row that triggered
        # it. The whole thing is a single top-to-bottom list.
        rows: List[str] = []
        for bid, branch in per.items():
            comparison = branch.get("comparison") or {}
            a = branch.get("copasi") or {}
            b = branch.get("tellurium") or {}
            fig = _build_figure(
                _series_by_species(a), a.get("time") or [], "COPASI",
                _series_by_species(b), b.get("time") or [], "Tellurium",
            )
            rows.append(_card_html(bid, comparison))
            rows.append(_detail_html(bid, fig))

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
            f'</div>'
            f'<script>{get_plotlyjs()}</script>'
            f'<script>{_TOGGLE_JS}</script>'
            f'</div>'
        )}
