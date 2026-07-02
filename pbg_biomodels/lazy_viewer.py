"""Served lazy viewer for two-tier batch-comparison output.

Reads the compact ``index.json`` to render the sortable / kind-filterable
overview + cross-engine tables instantly (no series in memory). Each model's
time series live in ``series/<bid>.parquet`` and are fetched + rendered only
when that model is opened — so the UI scales to all 1054 BioModels.

Reuses the figure + analysis builders from ``batch_compare_overlay`` server-side
(the parquet is reconstituted into per-job leaves and fed to the same code), so
the plots and cross-engine rollups match the self-contained report exactly.

Run:
    python -m pbg_biomodels.lazy_viewer --out-dir out/compare_all --port 8900
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse, parse_qs

from plotly.offline import get_plotlyjs

from pbg_biomodels.visualizations import batch_compare_overlay as bco


def _load_index(out_dir: Path) -> Dict[str, Any]:
    return json.loads((out_dir / "index.json").read_text(encoding="utf-8"))


def _parquet_leaves_aligned(out_dir: Path, bid: str) -> Dict[str, Dict[str, Dict[str, list]]]:
    """Reconstitute ``{job: {engine: {time:[...], var:[...]}}}`` from parquet."""
    import pyarrow.parquet as pq
    if not (out_dir / "series" / f"{bid}.parquet").is_file():
        return {}
    t = pq.read_table(out_dir / "series" / f"{bid}.parquet").to_pydict()
    jobs: Dict[str, Dict[str, Dict[str, list]]] = {}
    # times keyed by (job, engine) — identical across that engine's variables.
    seen_time: Dict[tuple, list] = {}
    for job, eng, var, tm, val in zip(t["job"], t["engine"], t["variable"],
                                      t["time"], t["value"]):
        leaf = jobs.setdefault(job, {}).setdefault(eng, {})
        leaf.setdefault(var, []).append(float(val))
        key = (job, eng)
        seen_time.setdefault(key, [])
        # the first variable encountered defines the time axis for this engine.
        if var == next(iter(leaf)):
            seen_time[key].append(float(tm))
    import math
    for (job, eng), times in seen_time.items():
        # steady-state rows carry NaN times — leave the "time" key off so
        # is_utc() correctly reports steady-state and the bar figure is used.
        if times and not all(math.isnan(x) for x in times):
            jobs[job][eng]["time"] = times
    return jobs


# Cap the small-multiples overlay so a many-observable model doesn't render
# thousands of Plotly traces (slow to build server-side AND to draw in-browser).
_MAX_OBSERVABLES = 24


def _cap_leaves(leaves: Dict[str, Any], n: int):
    """Trim each leaf to the first ``n`` observables (shared union order).

    Returns ``(capped_leaves, shown, total)``. Bounds figure size for models
    with hundreds of observables; the full series remain in the parquet.
    """
    from pbg_biomodels import result_leaf
    order: List[str] = []
    seen: set = set()
    for leaf in leaves.values():
        for k in result_leaf.observables_of(leaf):
            if k not in seen:
                seen.add(k)
                order.append(k)
    if len(order) <= n:
        return leaves, len(order), len(order)
    keep = set(order[:n])
    capped: Dict[str, Any] = {}
    for name, leaf in leaves.items():
        ax, _ = result_leaf.axis_of(leaf)
        capped[name] = {k: v for k, v in leaf.items() if k == ax or k in keep}
    return capped, n, len(order)


def _figure_for(out_dir: Path, bid: str, job: str,
                kind: str = "") -> Dict[str, Any]:
    """Build the Plotly figure for one (model, job), reusing the overlay code.

    A ``repeated_task`` job is a parameter scan: its axis (stored in the generic
    ``time`` parquet column) is the swept parameter, not time, so the overlay
    figure is reused and its x-axis relabeled to "scan parameter". The overlay
    is capped at ``_MAX_OBSERVABLES`` subplots to keep big models responsive.
    """
    from pbg_biomodels import result_leaf
    leaves = _parquet_leaves_aligned(out_dir, bid).get(job, {})
    live = {n: leaf for n, leaf in leaves.items() if leaf}
    color_map = bco._build_color_map(set(live.keys()))
    utc = {n: leaf for n, leaf in live.items() if result_leaf.is_utc(leaf)}
    if utc:
        capped, shown, total = _cap_leaves(utc, _MAX_OBSERVABLES)
        fig = bco._utc_overlay_figure(capped, color_map)
        if kind == "repeated_task":
            _relabel_scan_axis(fig)
        if shown < total:
            fig.setdefault("layout", {})["title"] = {
                "text": f"showing {shown} of {total} observables"}
        return fig
    return bco._ss_bar_figure(live, color_map)


def _relabel_scan_axis(fig: Dict[str, Any]) -> None:
    """Rename every x-axis title from "time" to "scan parameter" in-place."""
    layout = fig.get("layout") or {}
    for key, axis in layout.items():
        if key.startswith("xaxis") and isinstance(axis, dict):
            title = axis.get("title")
            if isinstance(title, dict) and title.get("text") == "time":
                title["text"] = "scan parameter"
            elif title == "time":
                axis["title"] = "scan parameter"


def _index_to_comparisons(index: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Reconstruct a ``comparisons[bid][job]`` map for the cross-engine tab."""
    out: Dict[str, Dict[str, Any]] = {}
    for bid, m in (index.get("models") or {}).items():
        out[bid] = {job: {"engines": j.get("engines") or [],
                          "matrix": j.get("matrix") or {}}
                    for job, j in (m.get("jobs") or {}).items()}
    return out


_CLOSENESS_LABELS = {"close": "Close (≤1)", "not_close": "Not close (>1)",
                     "error": "Error", "none": "—"}


def _engine_analysis_closeness(job_entry: Dict[str, Any]) -> Dict[str, Any]:
    """pbg↔pbg and pbg↔own-reference worst CLOSENESS score for one job,
    mirroring ``bco._engine_analysis`` but reading ``matrix_closeness``."""
    return bco._engine_analysis({
        "engines": job_entry.get("engines") or [],
        "matrix": job_entry.get("matrix_closeness") or {},
    })


def _run_table(index: Dict[str, Any], bid: str) -> str:
    """Per-engine execution + agreement table for one model, across its jobs.

    Execution: ✓ ran / ✗ <status> <error> / – absent (from ``runs``; when no
    provenance, engines listed in the job are shown as executed). The job's
    worst nRMSE and closeness are shown as the agreement summary line.
    """
    import html as _html

    m = (index.get("models") or {}).get(bid) or {}
    runs = m.get("runs") or {}
    out: List[str] = []
    for job, j in (m.get("jobs") or {}).items():
        listed = j.get("engines") or []
        job_runs = runs.get(job) or {}
        engs = sorted(set(listed) | set(job_runs.keys()))
        rows = []
        for e in engs:
            rec = job_runs.get(e)
            if rec is None:
                cell = ("<span class='ok'>✓ ran</span>" if e in listed
                        else "<span class='muted'>– absent</span>")
            elif (rec.get("status") or "") == "ok":
                cell = "<span class='ok'>✓ ran</span>"
            else:
                err = _html.escape(rec.get("error") or "")
                cell = (f"<span class='bad'>✗ {_html.escape(rec.get('status','failed'))}"
                        f"</span> <span class='small'>{err}</span>")
            rows.append(f"<tr><td>{_html.escape(e)}</td><td>{cell}</td></tr>")
        nr = j.get("max_nrmse")
        cl = j.get("max_score")
        nr_s = f"{nr:.4g}" if isinstance(nr, (int, float)) else "—"
        cl_s = f"{cl:.4g}" if isinstance(cl, (int, float)) else "—"
        out.append(
            f"<h4>{_html.escape(job)}</h4>"
            f"<div class='small'>worst nRMSE {nr_s} · worst closeness {cl_s}</div>"
            "<table><thead><tr><th>Engine</th><th>Execution</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>")
    return "".join(out) or "<div class='small'>no jobs</div>"


def _summary_stats(index: Dict[str, Any]) -> Dict[str, Any]:
    """Aggregate execution (per engine) + agreement (per metric bucket).

    Execution is counted as **distinct models** per engine (deduped across a
    model's jobs, so an engine that runs both the UTC and steady-state job of
    one model counts once). With per-engine ``runs`` present, ok vs failed is
    exact; on a salvaged index (no ``runs``) only "produced output" is known —
    ``provenance`` is False and ``failed`` stays 0 (unknowable)."""
    ran: Dict[str, set] = {}
    failed: Dict[str, set] = {}
    agreement: Dict[str, Dict[str, int]] = {"nrmse": {}, "closeness": {}}
    has_provenance = False

    def bump(d, k):
        d[k] = d.get(k, 0) + 1

    for bid, m in (index.get("models") or {}).items():
        runs = m.get("runs") or {}
        if runs:
            has_provenance = True
        for job, j in (m.get("jobs") or {}).items():
            bump(agreement["nrmse"], j.get("bucket") or "none")
            bump(agreement["closeness"], j.get("closeness_bucket") or "none")
            job_runs = runs.get(job) or {}
            if job_runs:
                for name, rec in job_runs.items():
                    tgt = ran if (rec.get("status") or "") == "ok" else failed
                    tgt.setdefault(name, set()).add(bid)
            else:  # salvaged: no per-engine status — infer produced-output
                for name in j.get("engines") or []:
                    ran.setdefault(name, set()).add(bid)

    names = sorted(set(ran) | set(failed))
    engines = {n: {"ran": len(ran.get(n, ())), "failed": len(failed.get(n, ()))}
               for n in names}
    return {"engines": engines, "agreement": agreement,
            "provenance": has_provenance}


def _summary_panel(index: Dict[str, Any]) -> str:
    s = _summary_stats(index)
    prov = s["provenance"]
    ran_header = "models ok" if prov else "models w/ output"
    note = "" if prov else (
        "<div class='small'>This dataset has no per-engine run provenance — "
        "counts are distinct models that produced output; failures are unknown. "
        "Re-run to capture per-engine status/errors.</div>")
    erows = "".join(
        f"<tr><td>{e}</td><td class='num'>{v['ran']}</td>"
        f"<td class='num'>{v['failed'] if prov else '—'}</td></tr>"
        for e, v in sorted(s["engines"].items()))

    def buckets(name):
        return "".join(
            f"<tr><td>{_CLOSENESS_LABELS.get(k, k)}</td><td class='num'>{n}</td></tr>"
            for k, n in sorted(s["agreement"][name].items()))

    return (
        "<h4>Execution (per engine)</h4>" + note +
        f"<table><thead><tr><th>Engine</th><th class='num'>{ran_header}</th>"
        "<th class='num'>failed</th></tr></thead>"
        f"<tbody>{erows}</tbody></table>"
        "<h4>Agreement — nRMSE</h4>"
        f"<table><tbody>{buckets('nrmse')}</tbody></table>"
        "<h4>Agreement — closeness</h4>"
        f"<table><tbody>{buckets('closeness')}</tbody></table>")


def _overview_rows(index: Dict[str, Any]) -> str:
    rows: List[str] = []
    for bid, m in (index.get("models") or {}).items():
        for job, j in (m.get("jobs") or {}).items():
            a = bco._engine_analysis({"engines": j.get("engines") or [],
                                      "matrix": j.get("matrix") or {}})
            pbg, self_n = a["pbg_pbg_max"], a["self_max"]
            bucket, label = bco.bucket_for(pbg)
            color = bco._BUCKET_COLOR.get(bucket, "#5d6573")
            kind = j.get("kind") or "utc"

            ac = _engine_analysis_closeness(j)
            cl_pbg, cl_self = ac["pbg_pbg_max"], ac["self_max"]
            cl_label = _CLOSENESS_LABELS.get(j.get("closeness_bucket") or "none", "—")

            def num(v):
                return f"{v:.4g}" if isinstance(v, (int, float)) else ""
            pbg_s = num(pbg) or "—"
            self_s = num(self_n) or "—"
            cl_pbg_s = num(cl_pbg) or "—"
            cl_self_s = num(cl_self) or "—"
            has_fail = int(j.get("n_failed", 0)) > 0
            diverged = (isinstance(pbg, (int, float)) and pbg > 0.10) or \
                (isinstance(cl_pbg, (int, float)) and cl_pbg > 1.0)
            rows.append(
                f'<tr class="ov-row" data-kind="{kind}" '
                f'data-pbg="{pbg if isinstance(pbg,(int,float)) else -1}" '
                f'data-self="{self_n if isinstance(self_n,(int,float)) else -1}" '
                f'data-clpbg="{cl_pbg if isinstance(cl_pbg,(int,float)) else -1}" '
                f'data-clself="{cl_self if isinstance(cl_self,(int,float)) else -1}" '
                f'data-fail="{1 if has_fail else 0}" '
                f'data-diverged="{1 if diverged else 0}" '
                f'onclick="openModel(this,\'{bid}\')" style="cursor:pointer;">'
                f'<td>{bid}</td><td>{job}</td>'
                f'<td><span class="kind-tag">{kind}</span></td>'
                f'<td><span class="dot" style="background:{color}"></span>{label}</td>'
                f'<td class="num">{pbg_s}</td><td class="num">{self_s}</td>'
                f'<td>{cl_label}</td>'
                f'<td class="num">{cl_pbg_s}</td><td class="num">{cl_self_s}</td>'
                f'<td class="num">{j.get("n_ok",0)}</td>'
                f'<td class="num">{j.get("n_failed",0)}</td></tr>'
                f'<tr class="detail-row" style="display:none;"><td colspan="11">'
                f'<div class="detail" id="detail-{bid}"></div></td></tr>'
            )
    return "".join(rows)


def _page(index: Dict[str, Any], static: bool = False) -> str:
    meta = index.get("meta") or {}
    n = len(index.get("models") or {})
    crashed = meta.get("crashed_models") or []
    cross = bco._cross_engine_tab_html(_index_to_comparisons(index),
                                       list((index.get("models") or {}).keys()))
    # Server mode hits /api/* endpoints; static mode fetches a pre-rendered
    # figures/<bid>.json ({job: plotly_fig}) sitting next to index.html.
    if static:
        open_js = (
            "function openModel(row,bid){var d=row.nextElementSibling;"
            "var open=d.style.display!=='none';d.style.display=open?'none':'';"
            "if(open)return;var box=document.getElementById('detail-'+bid);"
            "if(box.dataset.loaded)return;box.textContent='loading…';"
            "fetch('figures/'+bid+'.json').then(r=>r.json()).then(function(figs){"
            "box.innerHTML='';box.dataset.loaded='1';"
            "fetch('runs/'+bid+'.html').then(r=>r.text()).then(function(h){"
            "var t=document.createElement('div');t.innerHTML=h;box.insertBefore(t,box.firstChild);}).catch(function(){});"
            "Object.keys(figs).forEach(function(job){var div=document.createElement('div');"
            "div.id='plot-'+bid+'-'+job;box.appendChild(div);var fig=figs[job];"
            "Plotly.newPlot(div.id,fig.data,fig.layout,{responsive:true,displaylogo:false});});"
            "}).catch(function(){box.textContent='no series for this model';});}"
        )
    else:
        open_js = (
            "function openModel(row,bid){var d=row.nextElementSibling;"
            "var open=d.style.display!=='none';d.style.display=open?'none':'';"
            "if(open)return;var box=document.getElementById('detail-'+bid);"
            "if(box.dataset.loaded)return;box.textContent='loading…';"
            "fetch('/api/jobs/'+bid).then(r=>r.json()).then(function(jobs){"
            "box.innerHTML='';box.dataset.loaded='1';"
            "fetch('/api/runs/'+bid).then(r=>r.text()).then(function(h){"
            "var t=document.createElement('div');t.innerHTML=h;box.insertBefore(t,box.firstChild);}).catch(function(){});"
            "jobs.forEach(function(job){var div=document.createElement('div');"
            "div.id='plot-'+bid+'-'+job;box.appendChild(div);"
            "fetch('/api/figure/'+bid+'?job='+encodeURIComponent(job)).then(r=>r.json())"
            ".then(function(fig){Plotly.newPlot(div.id,fig.data,fig.layout,{responsive:true,displaylogo:false});});});});}"
        )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>BioModels comparison — {n} models</title>
<style>
 body{{font-family:-apple-system,sans-serif;margin:18px;color:#222;}}
 table{{border-collapse:collapse;width:100%;font-size:13px;}}
 th,td{{padding:6px 10px;text-align:left;border-bottom:1px solid #eef0f2;}}
 th{{cursor:pointer;border-bottom:2px solid #d0d4d9;color:#555;font-size:12px;user-select:none;}}
 td.num,th.num{{text-align:right;}}
 .dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;}}
 .kind-tag{{font-size:11px;padding:1px 6px;border-radius:8px;background:#eef;color:#446;}}
 .tab{{padding:6px 14px;border:none;background:none;font-size:13px;cursor:pointer;border-bottom:2px solid transparent;}}
 .tab.active{{border-bottom:2px solid #1b6e3c;font-weight:600;}}
 .pane{{display:none;}} .pane.active{{display:block;}}
 .detail{{padding:8px 4px;}}
 .controls{{margin:8px 0;font-size:13px;}}
 .ok{{color:#2e7d32;}} .bad{{color:#c62828;}} .muted{{color:#9aa0a6;}}
 .small{{color:#666;font-size:12px;}}
</style></head><body>
<h3>BioModels batch comparison — {n} models{' · '+str(len(crashed))+' crashed' if crashed else ''}</h3>
<div>
 <button class="tab active" onclick="showTab(event,'overview')">Overview</button>
 <button class="tab" onclick="showTab(event,'summary')">Summary</button>
 <button class="tab" onclick="showTab(event,'cross')">Cross-engine</button>
</div>
<div id="overview" class="pane active">
 <div class="controls">Kind:
  <select id="kindFilter" onchange="applyFilter()">
   <option value="all">all</option><option value="utc">utc</option>
   <option value="steady_state">steady_state</option>
   <option value="repeated_task">repeated_task</option>
  </select>
  &nbsp;<label><input type="checkbox" id="failFilter" onchange="applyFilter()"> only failures</label>
  &nbsp;<label><input type="checkbox" id="divFilter" onchange="applyFilter()"> only diverged</label>
  &nbsp;<span id="count"></span></div>
 <table id="ovtable"><thead><tr>
  <th onclick="sortBy(0,'s')">Biomodel</th><th onclick="sortBy(1,'s')">Job</th>
  <th onclick="sortBy(2,'s')">Kind</th>
  <th onclick="sortBy(3,'d:pbg')">nRMSE (pbg↔pbg)</th>
  <th class="num" onclick="sortBy(4,'d:pbg')">pbg↔pbg</th>
  <th class="num" onclick="sortBy(5,'d:self')">pbg↔ref</th>
  <th onclick="sortBy(6,'d:clpbg')">Closeness</th>
  <th class="num" onclick="sortBy(7,'d:clpbg')">cl pbg↔pbg</th>
  <th class="num" onclick="sortBy(8,'d:clself')">cl pbg↔ref</th>
  <th class="num" onclick="sortBy(9,'n')">OK</th>
  <th class="num" onclick="sortBy(10,'n')">failed</th>
 </tr></thead><tbody id="ovbody">{_overview_rows(index)}</tbody></table>
</div>
<div id="summary" class="pane">{_summary_panel(index)}</div>
<div id="cross" class="pane">{cross}</div>
<script>{get_plotlyjs()}</script>
<script>
function showTab(e,id){{document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
 e.target.classList.add('active');
 document.querySelectorAll('.pane').forEach(p=>p.classList.remove('active'));
 document.getElementById(id).classList.add('active');}}
function applyFilter(){{var k=document.getElementById('kindFilter').value,c=0;
 var onlyFail=document.getElementById('failFilter').checked;
 var onlyDiv=document.getElementById('divFilter').checked;
 document.querySelectorAll('#ovbody .ov-row').forEach(function(r){{
  var show=(k==='all'||r.dataset.kind===k);
  if(onlyFail) show=show&&r.dataset.fail==='1';
  if(onlyDiv) show=show&&r.dataset.diverged==='1';
  r.style.display=show?'':'none';
  r.nextElementSibling.style.display='none';
  if(show)c++;}});
 document.getElementById('count').textContent=c+' rows';}}
var _sortState={{col:-1,dir:1}};
function _sortVal(r,col,spec){{
 if(spec.slice(0,2)==='d:'){{var v=parseFloat(r.dataset[spec.slice(2)]);return (isNaN(v)||v<0)?null:v;}}
 if(spec==='n'){{var t=r.children[col].textContent.trim();if(t===''||t==='—')return null;var v=parseFloat(t);return isNaN(v)?null:v;}}
 return r.children[col].textContent.toLowerCase();}}
function sortBy(col,spec){{
 var isStr=(spec==='s');
 // new column: strings ascending, numbers descending (worst first); else toggle.
 var dir=(_sortState.col===col)?-_sortState.dir:(isStr?1:-1);
 _sortState={{col:col,dir:dir}};
 var body=document.getElementById('ovbody');
 var rows=Array.from(body.querySelectorAll('.ov-row'));
 rows.sort(function(a,b){{
  var av=_sortVal(a,col,spec),bv=_sortVal(b,col,spec);
  if(isStr){{return dir*(av<bv?-1:av>bv?1:0);}}
  if(av===null&&bv===null)return 0;
  if(av===null)return 1;   // missing (—) always sorts last
  if(bv===null)return -1;
  return dir*(av-bv);}});
 rows.forEach(function(r){{body.appendChild(r);body.appendChild(r.nextElementSibling);}});
 document.querySelectorAll('#ovtable thead th').forEach(function(th,i){{
  if(th.dataset.base===undefined)th.dataset.base=th.textContent;
  th.textContent=th.dataset.base+(i===col?(dir>0?' ▲':' ▼'):'');}});}}
{open_js}
applyFilter();
</script></body></html>"""


def make_handler(out_dir: Path):
    index = _load_index(out_dir)
    fig_cache: Dict[tuple, str] = {}  # (bid, job) -> figure JSON (built once)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, body, ctype="application/json"):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urlparse(self.path)
            p = u.path
            try:
                if p == "/" or p == "/index.html":
                    return self._send(_page(index), "text/html; charset=utf-8")
                if p.startswith("/api/jobs/"):
                    bid = p.rsplit("/", 1)[-1]
                    jobs = list(((index.get("models") or {}).get(bid) or {}).get("jobs") or {})
                    return self._send(json.dumps(jobs))
                if p.startswith("/api/runs/"):
                    bid = p.rsplit("/", 1)[-1]
                    return self._send(_run_table(index, bid),
                                      "text/html; charset=utf-8")
                if p.startswith("/api/figure/"):
                    bid = p.rsplit("/", 1)[-1]
                    job = (parse_qs(u.query).get("job") or [""])[0]
                    cached = fig_cache.get((bid, job))
                    if cached is None:
                        kind = (((index.get("models") or {}).get(bid) or {})
                                .get("jobs") or {}).get(job, {}).get("kind") or ""
                        cached = json.dumps(_figure_for(out_dir, bid, job, kind))
                        fig_cache[(bid, job)] = cached
                    return self._send(cached)
                self.send_error(404)
            except Exception as e:  # don't kill the server on a bad model
                self.send_error(500, str(e))

    return H


def serve(out_dir: str, port: int = 8900) -> None:
    od = Path(out_dir)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(od))
    print(f"Lazy viewer for {od} → http://127.0.0.1:{port}  (Ctrl-C to stop)")
    httpd.serve_forever()


def export_static(out_dir: str, dest: str) -> dict:
    """Render a fully static site (no server) from two-tier output.

    Writes ``dest/index.html`` (overview + cross-engine tables, sortable +
    kind-filterable) and one ``dest/figures/<bid>.json`` ({job: plotly_fig}) per
    model. Pure static files — host on GitHub Pages / Cloudflare; the page
    fetches a model's figure JSON on click. The huge per-model series never
    inline into the page.
    """
    od = Path(out_dir)
    dst = Path(dest)
    (dst / "figures").mkdir(parents=True, exist_ok=True)
    (dst / "runs").mkdir(parents=True, exist_ok=True)
    index = _load_index(od)
    (dst / "index.html").write_text(_page(index, static=True), encoding="utf-8")
    n_fig = 0
    for bid, m in (index.get("models") or {}).items():
        figs = {}
        for job, j in (m.get("jobs") or {}).items():
            try:
                figs[job] = _figure_for(od, bid, job, j.get("kind") or "")
            except Exception:
                pass
        (dst / "figures" / f"{bid}.json").write_text(json.dumps(figs), encoding="utf-8")
        # per-engine execution + agreement table (drill-down), fetched on click
        (dst / "runs" / f"{bid}.html").write_text(_run_table(index, bid), encoding="utf-8")
        n_fig += len(figs)
    return {"models": len(index.get("models") or {}), "figures": n_fig,
            "dest": str(dst)}


# --------------------------------------------------------------------------- #
# Browser-parquet static export (GitHub Pages): index.html + series/*.parquet.  #
# The page reads each model's parquet in-browser (hyparquet + zstd compressors) #
# and builds the Plotly figure client-side — a JS port of the overlay builders. #
# --------------------------------------------------------------------------- #

_BROWSER_JS = r"""
<script type="module">
import { parquetReadObjects, asyncBufferFromUrl } from 'https://cdn.jsdelivr.net/npm/hyparquet@1.17.1/src/index.min.js';
import { compressors } from 'https://cdn.jsdelivr.net/npm/hyparquet-compressors@1.1.1/src/index.min.js';
const COLORS = __COLORS__;
const cache = {};

async function loadParquet(bid){
  if(cache[bid]) return cache[bid];
  const file = await asyncBufferFromUrl({ url: 'series/'+bid+'.parquet' });
  const rows = await parquetReadObjects({ file, compressors });
  const jobs = {}, meta = {};
  for(const r of rows){
    const job=r.job, eng=r.engine, v=r.variable;
    (jobs[job]=jobs[job]||{}); (jobs[job][eng]=jobs[job][eng]||{});
    const leaf=jobs[job][eng];
    (leaf[v]=leaf[v]||[]).push(r.value);
    const key=job+''+eng;
    if(!meta[key]) meta[key]={first:v, t:[]};
    if(meta[key].first===v && !Number.isNaN(r.time)) meta[key].t.push(r.time);
  }
  for(const key in meta){ const [job,eng]=key.split(''); const t=meta[key].t;
    if(t.length) jobs[job][eng].time=t; }   // no time => steady-state
  cache[bid]=jobs; return jobs;
}
const isUtc = leaf => 'time' in leaf;
const obsOf = leaf => { const o={}; for(const k in leaf) if(k!=='time') o[k]=leaf[k]; return o; };

function utcFigure(leaves){
  const order=[], seen=new Set();
  for(const e in leaves) for(const sp in obsOf(leaves[e])) if(!seen.has(sp)){seen.add(sp);order.push(sp);}
  if(!order.length) return {data:[],layout:{title:'No observables'}};
  const cols=3, rows=Math.ceil(order.length/cols);
  const layout={grid:{rows,columns:cols,pattern:'independent'},height:220*rows+100,
    legend:{orientation:'h',y:1.04,x:0},margin:{t:60,b:40,l:60,r:20}};
  const traces=[], legseen=new Set();
  order.forEach((sp,i)=>{ const idx=i+1, xr=idx===1?'x':'x'+idx, yr=idx===1?'y':'y'+idx;
    layout['yaxis'+(idx===1?'':idx)]={title:{text:sp}};
    layout['xaxis'+(idx===1?'':idx)]={title:{text:'time'}};
    for(const e in leaves){ const leaf=leaves[e], y=obsOf(leaf)[sp], t=leaf.time;
      if(!y||!t) continue;
      traces.push({x:t,y:y,mode:'lines',name:e,legendgroup:e,
        showlegend:!legseen.has(e),line:{color:COLORS[e]},xaxis:xr,yaxis:yr});
      legseen.add(e); } });
  return {data:traces,layout};
}
function ssFigure(leaves){
  const order=[], seen=new Set(), scal={};
  for(const e in leaves){ const o=obsOf(leaves[e]); scal[e]={};
    for(const sp in o){ scal[e][sp]=o[sp][o[sp].length-1]; if(!seen.has(sp)){seen.add(sp);order.push(sp);} } }
  if(!order.length) return {data:[],layout:{title:'No observables'}};
  const traces=Object.keys(scal).map(e=>({type:'bar',name:e,x:order,
    y:order.map(sp=>scal[e][sp]||0),marker:{color:COLORS[e]}}));
  return {data:traces,layout:{barmode:'group',height:360}};
}
window.openModel=function(row,bid){
  const d=row.nextElementSibling, open=d.style.display!=='none';
  d.style.display=open?'none':''; if(open) return;
  const box=document.getElementById('detail-'+bid);
  if(box.dataset.loaded) return; box.textContent='loading…';
  loadParquet(bid).then(jobs=>{ box.innerHTML=''; box.dataset.loaded='1';
    Object.keys(jobs).forEach(job=>{ const div=document.createElement('div');
      div.id='plot-'+bid+'-'+job; const h=document.createElement('div');
      h.style.cssText='font-size:12px;color:#666;margin:6px 0;'; h.textContent=job; box.appendChild(h); box.appendChild(div);
      const live={}; for(const e in jobs[job]) if(Object.keys(jobs[job][e]).length) live[e]=jobs[job][e];
      const anyUtc=Object.values(live).some(isUtc);
      const fig=anyUtc?utcFigure(live):ssFigure(live);
      Plotly.newPlot(div.id,fig.data,fig.layout,{responsive:true,displaylogo:false}); }); })
   .catch(e=>{ box.textContent='failed to load series: '+e; });
};
</script>
"""


_UTIL_JS = """
function showTab(e,id){document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
 e.target.classList.add('active');document.querySelectorAll('.pane').forEach(p=>p.classList.remove('active'));
 document.getElementById(id).classList.add('active');}
function applyFilter(){var k=document.getElementById('kindFilter').value,c=0;
 document.querySelectorAll('#ovbody .ov-row').forEach(function(r){var show=(k==='all'||r.dataset.kind===k);
  r.style.display=show?'':'none';r.nextElementSibling.style.display='none';if(show)c++;});
 document.getElementById('count').textContent=c+' rows';}
function sortBy(col,type){var body=document.getElementById('ovbody');
 var rows=Array.from(body.querySelectorAll('.ov-row'));
 rows.sort(function(a,b){if(type==='pbg'||type==='self'){return parseFloat(b.dataset[type])-parseFloat(a.dataset[type]);}
  return a.children[col].textContent.localeCompare(b.children[col].textContent);});
 rows.forEach(function(r){body.appendChild(r);body.appendChild(r.nextElementSibling);});}
"""


def _browser_page(index: Dict[str, Any], color_map: Dict[str, str]) -> str:
    n = len(index.get("models") or {})
    crashed = (index.get("meta") or {}).get("crashed_models") or []
    cross = bco._cross_engine_tab_html(_index_to_comparisons(index),
                                       list((index.get("models") or {}).keys()))
    title = (index.get("meta") or {}).get("title") or f"BioModels batch comparison — {n} models"
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{title}</title>"
            "<style>"
            "body{font-family:-apple-system,sans-serif;margin:18px;color:#222;}"
            "table{border-collapse:collapse;width:100%;font-size:13px;}"
            "th,td{padding:6px 10px;text-align:left;border-bottom:1px solid #eef0f2;}"
            "th{cursor:pointer;border-bottom:2px solid #d0d4d9;color:#555;font-size:12px;user-select:none;}"
            "td.num,th.num{text-align:right;}"
            ".dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;}"
            ".kind-tag{font-size:11px;padding:1px 6px;border-radius:8px;background:#eef;color:#446;}"
            ".tab{padding:6px 14px;border:none;background:none;font-size:13px;cursor:pointer;border-bottom:2px solid transparent;}"
            ".tab.active{border-bottom:2px solid #1b6e3c;font-weight:600;}"
            ".pane{display:none;}.pane.active{display:block;}.detail{padding:8px 4px;}"
            ".controls{margin:8px 0;font-size:13px;}"
            "</style></head><body>"
            f"<h3>{title}{' · '+str(len(crashed))+' crashed' if crashed else ''}</h3>"
            "<div><button class='tab active' onclick=\"showTab(event,'overview')\">Overview</button>"
            "<button class='tab' onclick=\"showTab(event,'cross')\">Cross-engine</button></div>"
            "<div id='overview' class='pane active'>"
            "<div class='controls'>Kind: <select id='kindFilter' onchange='applyFilter()'>"
            "<option value='all'>all</option><option value='utc'>utc</option>"
            "<option value='steady_state'>steady_state</option></select> <span id='count'></span></div>"
            "<table><thead><tr>"
            "<th onclick=\"sortBy(0,'s')\">Biomodel</th><th onclick=\"sortBy(1,'s')\">Job</th>"
            "<th onclick=\"sortBy(2,'s')\">Kind</th><th>Status (pbg↔pbg)</th>"
            "<th class='num' onclick=\"sortBy(4,'pbg')\">pbg↔pbg</th>"
            "<th class='num' onclick=\"sortBy(5,'self')\">pbg↔ref</th>"
            "<th class='num' onclick=\"sortBy(6,'s')\">OK</th>"
            "<th class='num' onclick=\"sortBy(7,'s')\">failed</th>"
            f"</tr></thead><tbody id='ovbody'>{_overview_rows(index)}</tbody></table></div>"
            f"<div id='cross' class='pane'>{cross}</div>"
            f"<script>{get_plotlyjs()}</script>"
            f"<script>{_UTIL_JS}applyFilter();</script>"
            + _BROWSER_JS.replace("__COLORS__", json.dumps(color_map))
            + "</body></html>")


def export_static_parquet(out_dir: str, dest: str) -> dict:
    """Browser-parquet static site for GitHub Pages: index.html + series/*.parquet.

    The page reads each model's parquet in the browser (hyparquet + zstd) and
    renders figures client-side — no server, ~140 MB total (parquet unchanged).
    """
    import shutil
    od = Path(out_dir)
    dst = Path(dest)
    dst.mkdir(parents=True, exist_ok=True)
    index = _load_index(od)
    engines = set()
    for m in (index.get("models") or {}).values():
        for j in (m.get("jobs") or {}).values():
            engines.update(j.get("engines") or [])
    color_map = bco._build_color_map(engines)
    (dst / "index.html").write_text(_browser_page(index, color_map), encoding="utf-8")
    shutil.copytree(od / "series", dst / "series", dirs_exist_ok=True)
    return {"models": len(index.get("models") or {}), "dest": str(dst)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--port", type=int, default=8900)
    ap.add_argument("--export-static", default="",
                    help="render a static site to this dir instead of serving")
    ap.add_argument("--export-browser", default="",
                    help="render a browser-parquet static site (Pages) to this dir")
    a = ap.parse_args()
    if a.export_browser:
        info = export_static_parquet(a.out_dir, a.export_browser)
        print(f"browser-parquet site: {info['models']} models -> {info['dest']}")
        return 0
    if a.export_static:
        info = export_static(a.out_dir, a.export_static)
        print(f"static site: {info['models']} models, {info['figures']} figures "
              f"-> {info['dest']}")
        return 0
    serve(a.out_dir, a.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
