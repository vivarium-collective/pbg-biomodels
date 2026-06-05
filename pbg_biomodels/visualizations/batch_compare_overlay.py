"""BatchCompareOverlay — overview table + N-simulator multi-sedml-job card grid.

The viewer has two tabs:

* **Overview** — one row per ``(biomodel_id, sedml_job_id)`` with the worst-pair
  bucket, worst nRMSE, how many simulators produced output, and how many
  simulators FAILED on that model/job (a failed run leaves an empty results
  leaf).
* **Per-model** — each biomodel gets a card colored by its worst-pair bucket
  (aggregated across sedml jobs); clicking the card reveals a tab strip with
  one tab per sedml job, each rendering a per-observable overlay across the
  simulators that produced output. Steady-state observables render as a small
  grouped bar chart of final values instead of a line.

Inputs are the new nested store ``results[biomodel_id][sedml_job_id][simulator]``
where each leaf is a flat ``map[observable -> timeseries]`` (`results` type);
see `pbg_biomodels.result_leaf`. The HTML is a self-contained fragment that
includes Plotly inline.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from plotly.offline import get_plotlyjs

from pbg_biomodels import result_leaf
from pbg_superpowers.visualization import Visualization


_BUCKET_COLOR = {
    "good":       "#1b6e3c",
    "borderline": "#b8741a",
    "large":      "#b3261e",
    "none":       "#5d6573",
}

_BUCKET_RANK = {"good": 0, "borderline": 1, "large": 2, "none": -1}

# Stable per-simulator colors, shared with `pbg_biomodels.report._ENGINE_COLORS`
# so a given engine keeps the SAME color across every figure in the viewer
# (line overlays and steady-state bars alike). Unknown simulator names fall
# back to a deterministic palette assigned by sorted order.
_SIMULATOR_COLORS = {
    "copasi":    "#1f77b4",
    "tellurium": "#ff7f0e",
    "simbio":    "#2ca02c",
    "amici":     "#d62728",
}
_FALLBACK_COLORS = ["#9467bd", "#8c564b", "#e377c2", "#17becf", "#bcbd22"]


def _build_color_map(sim_names) -> Dict[str, str]:
    """Map each simulator name to a stable color used across all figures.

    Known engines get their canonical color; unknown names get deterministic
    fallbacks by sorted order so the same name always resolves to the same
    color regardless of which figure (or which biomodel) it appears in.
    """
    color_map: Dict[str, str] = {}
    fallback_i = 0
    for name in sorted(sim_names):
        if name in _SIMULATOR_COLORS:
            color_map[name] = _SIMULATOR_COLORS[name]
        else:
            color_map[name] = _FALLBACK_COLORS[fallback_i % len(_FALLBACK_COLORS)]
            fallback_i += 1
    return color_map


def _aggregate_card_bucket(per_doc_comparisons: Dict[str, Any]) -> Dict[str, Any]:
    """Pick the worst (largest-mean-nrmse) bucket across this biomodel's jobs."""
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
    sim_leaves: Dict[str, Dict[str, Any]],
    color_map: Dict[str, str],
) -> Dict[str, Any]:
    """Per-observable small-multiples overlay across simulators (UTC leaves)."""
    species_order: List[str] = []
    seen: set = set()
    for leaf in sim_leaves.values():
        for sp in result_leaf.observables_of(leaf).keys():
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
        for sim_name, leaf in sim_leaves.items():
            obs = result_leaf.observables_of(leaf)
            series = obs.get(sp)
            time = result_leaf.time_of(leaf)
            if series is None or not time:
                continue
            traces.append({
                "x": list(time), "y": list(series),
                "mode": "lines", "name": sim_name,
                "legendgroup": sim_name,
                "showlegend": sim_name not in seen_legend,
                "line": {"color": color_map.get(sim_name)},
                "xaxis": x_ref, "yaxis": y_ref,
            })
            seen_legend.add(sim_name)
    return {"data": traces, "layout": layout}


def _ss_bar_figure(
    sim_leaves: Dict[str, Dict[str, Any]],
    color_map: Dict[str, str],
) -> Dict[str, Any]:
    """Grouped bar chart of final steady-state values across simulators."""
    species: List[str] = []
    seen: set = set()
    scalars_by_sim = {n: result_leaf.steady_state_scalars(leaf)
                      for n, leaf in sim_leaves.items()}
    for sc in scalars_by_sim.values():
        for sp in sc.keys():
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
            "y":    [float(sc.get(sp, 0.0)) for sp in species],
            "marker": {"color": color_map.get(sim_name)},
        }
        for sim_name, sc in scalars_by_sim.items()
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


def _overview_row(
    bid: str,
    job: str,
    comparison: Dict[str, Any],
    n_ok: int,
    n_failed: int,
) -> str:
    """One overview-table row for a single (biomodel_id, sedml_job_id)."""
    bucket = (comparison or {}).get("bucket") or "none"
    label = (comparison or {}).get("bucket_label") or "No comparison"
    max_n = (comparison or {}).get("max_nrmse")
    max_str = f"{max_n:.4g}" if isinstance(max_n, (int, float)) else "—"
    color = _BUCKET_COLOR.get(bucket, "#5d6573")
    fail_color = "#b3261e" if n_failed else "#444"
    fail_weight = "600" if n_failed else "400"
    return (
        '<tr style="border-bottom:1px solid #eef0f2;">'
        f'<td style="padding:6px 10px;font-weight:600;">{bid}</td>'
        f'<td style="padding:6px 10px;font-family:ui-monospace,monospace;">{job}</td>'
        f'<td style="padding:6px 10px;"><span style="display:inline-block;'
        f'width:9px;height:9px;border-radius:50%;background:{color};'
        f'margin-right:6px;"></span>{label}</td>'
        f'<td style="padding:6px 10px;text-align:right;">{max_str}</td>'
        f'<td style="padding:6px 10px;text-align:right;">{n_ok}</td>'
        f'<td style="padding:6px 10px;text-align:right;color:{fail_color};'
        f'font-weight:{fail_weight};">{n_failed}</td>'
        '</tr>'
    )


def _git_str(g: Dict[str, Any]) -> str:
    """Render a {commit, dirty} git record (or em-dash when absent)."""
    if not g or not g.get("commit"):
        return "—"
    dirty = " <span style='color:#b3261e;'>(dirty)</span>" if g.get("dirty") else ""
    return f'<code>{g["commit"]}</code>{dirty}'


def _provenance_panel_html(diagnostics: Dict[str, Any]) -> str:
    """Host / when / platform context + a per-simulator version & git table."""
    meta = (diagnostics or {}).get("meta") or {}
    prov = (diagnostics or {}).get("provenance") or {}
    whens = [p.get("started_utc") for p in prov.values() if p.get("started_utc")]
    when = min(whens) if whens else "—"
    ctx = (
        '<div style="font-size:13px;color:#333;margin-bottom:12px;'
        'font-family:-apple-system,sans-serif;line-height:1.6;">'
        f'<b>Run:</b> {when} &nbsp;·&nbsp; <b>Host:</b> {meta.get("host","—")}<br>'
        f'<b>Platform:</b> {meta.get("platform","—")} &nbsp;·&nbsp; '
        f'<b>Python:</b> {meta.get("python","—")}'
        '</div>'
    )
    head = (
        '<tr style="text-align:left;border-bottom:2px solid #d0d4d9;'
        'font-size:12px;color:#555;">'
        '<th style="padding:6px 10px;">Simulator</th>'
        '<th style="padding:6px 10px;">Library</th>'
        '<th style="padding:6px 10px;">Wrapper</th>'
        '<th style="padding:6px 10px;">Wrapper commit</th>'
        '<th style="padding:6px 10px;text-align:right;">Total runtime (s)</th>'
        '</tr>'
    )
    rows = []
    for sim, p in prov.items():
        rt = p.get("total_runtime_s")
        rt_str = f"{rt:.3f}" if isinstance(rt, (int, float)) else "—"
        rows.append(
            '<tr style="border-bottom:1px solid #eef0f2;">'
            f'<td style="padding:6px 10px;font-weight:600;">{sim}</td>'
            f'<td style="padding:6px 10px;">{p.get("lib_version") or "—"}</td>'
            f'<td style="padding:6px 10px;">{p.get("wrapper") or "—"} '
            f'{p.get("wrapper_version") or ""}</td>'
            f'<td style="padding:6px 10px;">{_git_str(p.get("wrapper_git"))}</td>'
            f'<td style="padding:6px 10px;text-align:right;">{rt_str}</td>'
            '</tr>'
        )
    body = "".join(rows) or ('<tr><td colspan="5" style="padding:10px;color:#888;">'
                             'No provenance.</td></tr>')
    return (
        ctx +
        '<table style="border-collapse:collapse;width:100%;font-size:13px;'
        'font-family:-apple-system,sans-serif;">'
        f'<thead>{head}</thead><tbody>{body}</tbody></table>'
    )


def _runtime_table_html(diagnostics: Dict[str, Any]) -> str:
    """One row per (biomodel, sedml-job, simulator) with runtime + status."""
    runs = (diagnostics or {}).get("runs") or {}
    rows = []
    for bid in sorted(runs.keys()):
        for job, simmap in (runs[bid] or {}).items():
            for sim, rec in (simmap or {}).items():
                rt = rec.get("runtime_s")
                rt_str = f"{rt:.4f}" if isinstance(rt, (int, float)) else "—"
                status = rec.get("status") or "—"
                ok = status == "ok"
                sc = "#1b6e3c" if ok else "#b3261e"
                err = rec.get("error") or ""
                err_html = (f'<div style="color:#b3261e;font-size:11px;">{err}</div>'
                            if err else "")
                rows.append(
                    '<tr style="border-bottom:1px solid #eef0f2;">'
                    f'<td style="padding:6px 10px;font-weight:600;">{bid}</td>'
                    f'<td style="padding:6px 10px;font-family:ui-monospace,monospace;">{job}</td>'
                    f'<td style="padding:6px 10px;">{sim}</td>'
                    f'<td style="padding:6px 10px;text-align:right;">{rt_str}</td>'
                    f'<td style="padding:6px 10px;color:{sc};">{status}{err_html}</td>'
                    '</tr>'
                )
    head = (
        '<tr style="text-align:left;border-bottom:2px solid #d0d4d9;'
        'font-size:12px;color:#555;">'
        '<th style="padding:6px 10px;">Biomodel</th>'
        '<th style="padding:6px 10px;">SED-ML job</th>'
        '<th style="padding:6px 10px;">Simulator</th>'
        '<th style="padding:6px 10px;text-align:right;">Runtime (s)</th>'
        '<th style="padding:6px 10px;">Status</th>'
        '</tr>'
    )
    body = "".join(rows) or ('<tr><td colspan="5" style="padding:10px;color:#888;">'
                             'No runs.</td></tr>')
    return (
        '<table style="border-collapse:collapse;width:100%;font-size:13px;'
        'font-family:-apple-system,sans-serif;">'
        f'<thead>{head}</thead><tbody>{body}</tbody></table>'
    )


def _diagnostics_tab_html(diagnostics: Dict[str, Any]) -> str:
    return (
        '<h4 style="margin:4px 0 8px 0;font-family:-apple-system,sans-serif;">'
        'Provenance</h4>'
        + _provenance_panel_html(diagnostics) +
        '<h4 style="margin:18px 0 8px 0;font-family:-apple-system,sans-serif;">'
        'Per-simulation runtime</h4>'
        + _runtime_table_html(diagnostics)
    )


def _overview_table_html(rows: List[str]) -> str:
    """The Overview tab: a (biomodel × sedml-job) summary table."""
    if not rows:
        body = ('<tr><td colspan="6" style="padding:10px;color:#888;">'
                'No results.</td></tr>')
    else:
        body = "".join(rows)
    head = (
        '<tr style="text-align:left;border-bottom:2px solid #d0d4d9;'
        'font-size:12px;color:#555;">'
        '<th style="padding:6px 10px;">Biomodel</th>'
        '<th style="padding:6px 10px;">SED-ML job</th>'
        '<th style="padding:6px 10px;">Status</th>'
        '<th style="padding:6px 10px;text-align:right;">Worst nRMSE</th>'
        '<th style="padding:6px 10px;text-align:right;">Simulators OK</th>'
        '<th style="padding:6px 10px;text-align:right;">Simulators failed</th>'
        '</tr>'
    )
    return (
        '<table style="border-collapse:collapse;width:100%;font-size:13px;'
        'font-family:-apple-system,sans-serif;">'
        f'<thead>{head}</thead><tbody>{body}</tbody></table>'
    )


def _detail_html(bid: str, doc_figs: Dict[str, Dict[str, Any]]) -> str:
    """Render the tab strip + plot containers for one biomodel's sedml jobs."""
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
document.querySelectorAll('.batch-toptab').forEach(function(tab) {
  tab.addEventListener('click', function() {
    var target = tab.getAttribute('data-target');
    document.querySelectorAll('.batch-toptab').forEach(function(t) {
      t.style.borderBottom = '2px solid transparent'; t.style.fontWeight = '400';
    });
    tab.style.borderBottom = '2px solid #1b6e3c'; tab.style.fontWeight = '600';
    document.querySelectorAll('.batch-toppane').forEach(function(p) {
      p.style.display = 'none';
    });
    var pane = document.getElementById(target);
    if (pane) pane.style.display = 'block';
  });
});
"""


class BatchCompareOverlay(Visualization):
    """Overview table + N-simulator multi-sedml-job card-grid overlay.

    Inputs:
        results: `map[bid, map[sedml_job, map[sim, results]]]` — the nested
            store; each leaf is a flat `map[observable -> timeseries]`.
        comparisons: `map[bid, map[sedml_job, tree]]`.

    Output: a single `html` fragment.
    """

    config_schema = {
        "title":        {"_type": "string", "_default": ""},
        "biomodel_ids": {"_type": "list[string]", "_default": []},
    }

    def inputs(self) -> Dict[str, Any]:
        return {"results": "tree", "comparisons": "tree", "diagnostics": "tree"}

    def update(self, state: Dict[str, Any]) -> Dict[str, str]:
        results = state.get("results") or {}
        comparisons = state.get("comparisons") or {}
        diagnostics = state.get("diagnostics") or {}
        ids = list((self.config or {}).get("biomodel_ids") or []) or list(results.keys())

        if not ids or not results:
            return {"html":
                '<div style="padding:20px;color:#888;'
                'font-family:-apple-system,sans-serif;">'
                'No biomodels to compare.</div>'}

        # Build the simulator->color map once, over every simulator that appears
        # anywhere in the store, so coloring is consistent across all figures.
        all_sims = {
            sim
            for doc_map in results.values()
            for sim_leaves in (doc_map or {}).values()
            for sim in (sim_leaves or {})
        }
        color_map = _build_color_map(all_sims)

        overview_rows: List[str] = []
        detail_rows: List[str] = []
        for bid in ids:
            doc_map = results.get(bid) or {}
            doc_figs: Dict[str, Dict[str, Any]] = {}
            for doc, sim_leaves in doc_map.items():
                sim_leaves = sim_leaves or {}
                # A failed simulator run leaves an empty leaf; OK = produced output.
                n_failed = sum(1 for leaf in sim_leaves.values() if not leaf)
                n_ok = sum(1 for leaf in sim_leaves.values() if leaf)
                comparison = (comparisons.get(bid) or {}).get(doc) or {}
                overview_rows.append(
                    _overview_row(bid, doc, comparison, n_ok, n_failed))

                live = {n: leaf for n, leaf in sim_leaves.items() if leaf}
                if not live:
                    continue
                utc_only = {n: leaf for n, leaf in live.items()
                            if result_leaf.is_utc(leaf)}
                ss_only = {n: leaf for n, leaf in live.items()
                           if not result_leaf.is_utc(leaf)}
                # If both kinds appear, route to whichever has more engines;
                # cross-kind isn't a meaningful overlay so we just pick the
                # majority and let the minority drop. BatchCompareStep already
                # emits a warning + "none" bucket for this case.
                if utc_only and (not ss_only or len(utc_only) >= len(ss_only)):
                    doc_figs[doc] = _utc_overlay_figure(utc_only, color_map)
                elif ss_only:
                    doc_figs[doc] = _ss_bar_figure(ss_only, color_map)

            agg = _aggregate_card_bucket(comparisons.get(bid) or {})
            detail_rows.append(_card_html(bid, agg))
            detail_rows.append(_detail_html(bid, doc_figs))

        title = (self.config or {}).get("title", "")
        title_html = (
            f'<h3 style="margin:0 0 12px 0;font-family:-apple-system,sans-serif;">'
            f'{title}</h3>'
        ) if title else ''

        top_tabs = (
            '<div class="batch-toptab-strip" style="margin-bottom:12px;'
            'border-bottom:1px solid #e5e7eb;font-family:-apple-system,sans-serif;">'
            '<button class="batch-toptab" data-target="batch-overview" '
            'style="padding:6px 14px;font-size:13px;background:none;border:none;'
            'border-bottom:2px solid #1b6e3c;font-weight:600;cursor:pointer;">'
            'Overview</button>'
            '<button class="batch-toptab" data-target="batch-detail" '
            'style="padding:6px 14px;font-size:13px;background:none;border:none;'
            'border-bottom:2px solid transparent;cursor:pointer;">'
            'Per-model</button>'
            '<button class="batch-toptab" data-target="batch-diagnostics" '
            'style="padding:6px 14px;font-size:13px;background:none;border:none;'
            'border-bottom:2px solid transparent;cursor:pointer;">'
            'Diagnostics</button>'
            '</div>'
        )
        overview_pane = (
            '<div id="batch-overview" class="batch-toppane">'
            + _overview_table_html(overview_rows) +
            '</div>'
        )
        detail_pane = (
            '<div id="batch-detail" class="batch-toppane" style="display:none;">'
            '<div class="biomodel-list" style="'
            'display:flex;flex-direction:column;gap:4px;">'
            + "".join(detail_rows) +
            '</div></div>'
        )
        diagnostics_pane = (
            '<div id="batch-diagnostics" class="batch-toppane" style="display:none;">'
            + _diagnostics_tab_html(diagnostics) +
            '</div>'
        )
        return {"html": (
            f'<div>{title_html}{top_tabs}{overview_pane}{detail_pane}{diagnostics_pane}'
            f'<script>{get_plotlyjs()}</script>'
            f'<script>{_TOGGLE_JS}</script>'
            '</div>'
        )}
