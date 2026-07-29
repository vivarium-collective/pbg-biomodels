"""Self-contained navigable HTML report for a multi-simulator comparison.

``build_comparison_report`` takes the structure the CLI assembles from a
compare-simulators run::

    {
      "<biomodel_id>": {
        "engines": {"copasi": <numeric_result>, "tellurium": ..., ...},
        "comparison": <compare_n_engines result>,
      },
      ...
    }

and writes one HTML file with a sidebar of biomodels (grouped by worst-pair
nRMSE bucket), an overview table, and per-biomodel panels containing the
all-engine overlay plot, the all-pairs nRMSE matrix, and an individual plot per
simulator. Plotly is embedded for offline viewing; figures render lazily when a
panel is shown.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

# Stable per-engine colors (Plotly qualitative); references fall back to grey.
_ENGINE_COLORS = {
    "copasi": "#1f77b4",
    "tellurium": "#ff7f0e",
    "simbio": "#2ca02c",
    "amici": "#d62728",
}
_FALLBACK_COLORS = ["#9467bd", "#8c564b", "#e377c2", "#17becf", "#bcbd22"]

_BUCKET_COLOR = {
    "good": "#16a34a",
    "borderline": "#d97706",
    "large": "#dc2626",
    "none": "#6b7280",
}


def _engine_color(name: str, index: int) -> str:
    if name in _ENGINE_COLORS:
        return _ENGINE_COLORS[name]
    return _FALLBACK_COLORS[index % len(_FALLBACK_COLORS)]


def _series_by_species(payload: Dict[str, Any]) -> Dict[str, List[float]]:
    cols = payload.get("columns", []) or []
    values = payload.get("values", []) or []
    return {sp: [row[j] for row in values] for j, sp in enumerate(cols)}


def _species_union(engines: Dict[str, Any]) -> List[str]:
    species: List[str] = []
    seen = set()
    for payload in engines.values():
        for sp in (payload or {}).get("columns", []) or []:
            if sp not in seen:
                seen.add(sp)
                species.append(sp)
    return species


def _grid_layout(n: int, cols: int = 3) -> Dict[str, Any]:
    rows = max(1, (n + cols - 1) // cols)
    return {
        "grid": {"rows": rows, "columns": cols, "pattern": "independent"},
        "height": 240 * rows + 80,
        "margin": {"t": 50, "b": 40, "l": 55, "r": 15},
        "legend": {"orientation": "h", "y": 1.03, "x": 0},
    }


def _overlay_figure(engines: Dict[str, Any]) -> Dict[str, Any]:
    """All engines overlaid, one subplot per species."""
    species = _species_union(engines)
    if not species:
        return {"data": [], "layout": {"title": "No data"}}
    layout = _grid_layout(len(species))
    ordered = list(engines)
    series_by_engine = {name: _series_by_species(p or {}) for name, p in engines.items()}
    traces: List[Dict[str, Any]] = []
    seen_legend = set()
    for i, sp in enumerate(species):
        idx = i + 1
        suffix = "" if idx == 1 else str(idx)
        layout[f"xaxis{suffix}"] = {"title": {"text": "time"}}
        layout[f"yaxis{suffix}"] = {"title": {"text": sp}}
        for k, name in enumerate(ordered):
            ys = series_by_engine[name].get(sp)
            t = (engines[name] or {}).get("time")
            if ys is None or t is None:
                continue
            traces.append({
                "x": t, "y": ys, "mode": "lines", "name": name,
                "legendgroup": name, "showlegend": name not in seen_legend,
                "xaxis": f"x{suffix}", "yaxis": f"y{suffix}",
                "line": {"color": _engine_color(name, k)},
            })
            seen_legend.add(name)
    return {"data": traces, "layout": layout}


# Distinct, colorblind-friendly palette for per-species coloring (Plotly "Safe").
_SPECIES_PALETTE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b",
    "#e377c2", "#7f7f7f", "#bcbd22", "#17becf", "#393b79", "#637939",
    "#8c6d31", "#843c39", "#7b4173", "#5254a3", "#9c9ede", "#cedb9c",
]


def _species_color_map(species: List[str]) -> Dict[str, str]:
    """Assign each species a stable color, shared across the per-simulator plots."""
    return {sp: _SPECIES_PALETTE[i % len(_SPECIES_PALETTE)] for i, sp in enumerate(species)}


def _single_figure(name: str, payload: Dict[str, Any],
                   species_colors: Dict[str, str]) -> Dict[str, Any]:
    """One engine's species trajectories, colored by species (shared map)."""
    t = (payload or {}).get("time") or []
    series = _series_by_species(payload or {})
    traces = [
        {"x": t, "y": ys, "mode": "lines", "name": sp,
         "line": {"color": species_colors.get(sp)}}
        for sp, ys in series.items()
    ]
    return {
        "data": traces,
        "layout": {
            "title": {"text": name},
            "height": 320,
            "margin": {"t": 40, "b": 40, "l": 55, "r": 15},
            "xaxis": {"title": {"text": "time"}},
            "yaxis": {"title": {"text": "concentration"}},
        },
    }


def _fmt_nrmse(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v:.2e}" if v < 1e-3 else f"{v:.4f}"


def _matrix_table_html(comparison: Dict[str, Any]) -> str:
    engines = comparison.get("engines", []) or []
    matrix = comparison.get("matrix", {}) or {}
    if not engines:
        return '<p class="muted">No comparable engine pairs.</p>'
    head = "".join(f"<th>{html.escape(e)}</th>" for e in engines)
    rows = []
    for a in engines:
        cells = []
        for b in engines:
            if a == b:
                cells.append('<td class="diag">·</td>')
            else:
                cells.append(f"<td>{_fmt_nrmse(matrix.get(a, {}).get(b))}</td>")
        rows.append(f"<tr><th>{html.escape(a)}</th>{''.join(cells)}</tr>")
    return (
        '<table class="matrix"><thead><tr><th>nRMSE</th>'
        f"{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def _bucket_badge(comparison: Dict[str, Any]) -> str:
    bucket = comparison.get("bucket", "none")
    label = comparison.get("bucket_label", bucket)
    worst = comparison.get("worst_pair")
    color = _BUCKET_COLOR.get(bucket, "#6b7280")
    worst_txt = f" · worst: {html.escape(' vs '.join(worst))}" if worst else ""
    return (
        f'<span class="badge" style="background:{color}">{html.escape(label)}'
        f"</span><span class='muted'>{worst_txt}</span>"
    )


def build_comparison_report(
    results: Dict[str, Dict[str, Any]],
    output_path: str,
    title: str = "BioModels simulator comparison",
) -> Path:
    """Render the navigable comparison report. Returns the written path."""
    try:
        from plotly.offline import get_plotlyjs
        plotly_js = get_plotlyjs()
        plotly_script = f"<script>{plotly_js}</script>"
    except Exception:
        plotly_script = (
            '<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>'
        )

    figures: Dict[str, Any] = {}
    sidebar_items: List[str] = []
    overview_rows: List[str] = []
    panels: List[str] = []

    for bid, branch in results.items():
        engines = branch.get("engines", {}) or {}
        comparison = branch.get("comparison", {}) or {}
        error = branch.get("error")
        bucket = "error" if error else comparison.get("bucket", "none")
        color = "#dc2626" if error else _BUCKET_COLOR.get(bucket, "#6b7280")

        if error:
            sidebar_items.append(
                f'<a class="nav" data-target="m-{html.escape(bid)}">'
                f'<span class="dot" style="background:{color}"></span>{html.escape(bid)}</a>'
            )
            overview_rows.append(
                f"<tr data-target='m-{html.escape(bid)}'><td>{html.escape(bid)}</td>"
                f"<td>0</td><td>—</td>"
                f"<td><span class='badge' style='background:{color}'>error</span></td></tr>"
            )
            panels.append(
                f'<section class="panel" id="m-{html.escape(bid)}">'
                f"<h2>{html.escape(bid)}</h2>"
                f'<p><span class="badge" style="background:{color}">error</span></p>'
                f'<pre class="err">{html.escape(error)}</pre></section>'
            )
            continue

        # Sidebar + overview row.
        sidebar_items.append(
            f'<a class="nav" data-target="m-{html.escape(bid)}">'
            f'<span class="dot" style="background:{color}"></span>{html.escape(bid)}</a>'
        )
        overview_rows.append(
            f"<tr data-target='m-{html.escape(bid)}'><td>{html.escape(bid)}</td>"
            f"<td>{len(engines)}</td>"
            f"<td>{_fmt_nrmse(comparison.get('max_nrmse'))}</td>"
            f"<td><span class='badge' style='background:{color}'>"
            f"{html.escape(comparison.get('bucket_label', bucket))}</span></td></tr>"
        )

        # Figures (rendered lazily by id).
        overlay_id = f"overlay-{bid}"
        figures[overlay_id] = _overlay_figure(engines)
        # Per-species colors shared across this model's individual plots, so a
        # species reads the same color in every simulator's subplot.
        species_colors = _species_color_map(_species_union(engines))
        single_divs = []
        for name, payload in engines.items():
            fid = f"single-{bid}-{name}"
            figures[fid] = _single_figure(name, payload, species_colors)
            single_divs.append(
                f'<div class="plot" id="{fid}" data-fig="{fid}"></div>'
            )

        panels.append(f"""
        <section class="panel" id="m-{html.escape(bid)}">
          <h2>{html.escape(bid)}</h2>
          <p>{_bucket_badge(comparison)}</p>
          <h3>All-pairs nRMSE</h3>
          {_matrix_table_html(comparison)}
          <h3>Overlay — all simulators</h3>
          <div class="plot" id="{overlay_id}" data-fig="{overlay_id}"></div>
          <h3>Individual simulator results</h3>
          <div class="singles">{''.join(single_divs)}</div>
        </section>""")

    figures_json = json.dumps(figures).replace("</", "<\\/")
    html_doc = _TEMPLATE.format(
        title=html.escape(title),
        plotly_script=plotly_script,
        n=len(results),
        sidebar="".join(sidebar_items),
        overview_rows="".join(overview_rows),
        panels="".join(panels),
        figures_json=figures_json,
    )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_doc, encoding="utf-8")
    return out


_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{plotly_script}
<style>
  body {{ margin:0; font-family:-apple-system,Segoe UI,Roboto,sans-serif; color:#0f172a; }}
  .layout {{ display:flex; min-height:100vh; }}
  nav {{ width:260px; background:#0f172a; color:#e2e8f0; padding:18px 14px; position:sticky; top:0; height:100vh; overflow:auto; }}
  nav h1 {{ font-size:15px; margin:0 0 12px; }}
  nav .nav, nav .overview-link {{ display:block; color:#cbd5e1; text-decoration:none; padding:6px 8px; border-radius:6px; font-size:13px; }}
  nav .nav:hover, nav .nav.active, nav .overview-link.active {{ background:#1e293b; color:#fff; }}
  nav .dot {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:8px; }}
  main {{ flex:1; padding:24px 32px; max-width:1100px; }}
  .panel {{ display:none; }} .panel.active {{ display:block; }}
  h2 {{ margin:0 0 6px; }} h3 {{ margin:22px 0 8px; font-size:15px; color:#334155; }}
  .muted {{ color:#64748b; font-size:13px; }}
  .badge {{ color:#fff; padding:2px 9px; border-radius:10px; font-size:12px; font-weight:600; }}
  table {{ border-collapse:collapse; font-size:13px; }}
  th, td {{ border:1px solid #e2e8f0; padding:5px 10px; text-align:right; }}
  th {{ background:#f8fafc; }}
  table.matrix td.diag {{ color:#cbd5e1; }}
  table.overview {{ width:100%; }} table.overview td:first-child, table.overview th:first-child {{ text-align:left; }}
  table.overview tbody tr {{ cursor:pointer; }} table.overview tbody tr:hover {{ background:#f1f5f9; }}
  .err {{ background:#fef2f2; color:#991b1b; padding:12px; border-radius:6px; font-size:12px; overflow:auto; }}
  .plot {{ width:100%; margin:6px 0 16px; }}
  .singles {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
  @media (max-width:900px) {{ .singles {{ grid-template-columns:1fr; }} }}
</style></head>
<body>
<div class="layout">
  <nav>
    <h1>{title}</h1>
    <a class="overview-link active" data-target="overview">Overview ({n})</a>
    {sidebar}
  </nav>
  <main>
    <section class="panel active" id="overview">
      <h2>Overview</h2>
      <p class="muted">{n} biomodel(s). Click a row or the sidebar to view a model's
        overlay, nRMSE matrix, and per-simulator plots.</p>
      <table class="overview"><thead><tr><th>BioModel</th><th>#engines</th>
        <th>max nRMSE</th><th>worst-pair bucket</th></tr></thead>
        <tbody>{overview_rows}</tbody></table>
    </section>
    {panels}
  </main>
</div>
<script type="application/json" id="figures">{figures_json}</script>
<script>
  var FIGS = JSON.parse(document.getElementById("figures").textContent);
  var drawn = {{}};
  function draw(panel) {{
    panel.querySelectorAll(".plot").forEach(function(el) {{
      var id = el.getAttribute("data-fig");
      if (drawn[id] || !FIGS[id]) return;
      Plotly.newPlot(el, FIGS[id].data, FIGS[id].layout, {{displayModeBar:false, responsive:true}});
      drawn[id] = true;
    }});
  }}
  function show(target) {{
    document.querySelectorAll(".panel").forEach(function(p) {{ p.classList.toggle("active", p.id === target); }});
    document.querySelectorAll("nav a").forEach(function(a) {{ a.classList.toggle("active", a.getAttribute("data-target") === target); }});
    var panel = document.getElementById(target);
    if (panel) draw(panel);
    window.scrollTo(0, 0);
  }}
  document.querySelectorAll("[data-target]").forEach(function(el) {{
    el.addEventListener("click", function() {{ show(el.getAttribute("data-target")); }});
  }});
</script>
</body></html>"""
