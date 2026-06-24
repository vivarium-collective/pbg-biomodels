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


def _figure_for(out_dir: Path, bid: str, job: str) -> Dict[str, Any]:
    """Build the Plotly figure for one (model, job), reusing the overlay code."""
    from pbg_biomodels import result_leaf
    leaves = _parquet_leaves_aligned(out_dir, bid).get(job, {})
    live = {n: leaf for n, leaf in leaves.items() if leaf}
    color_map = bco._build_color_map(set(live.keys()))
    utc = {n: leaf for n, leaf in live.items() if result_leaf.is_utc(leaf)}
    if utc:
        return bco._utc_overlay_figure(utc, color_map)
    return bco._ss_bar_figure(live, color_map)


def _index_to_comparisons(index: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Reconstruct a ``comparisons[bid][job]`` map for the cross-engine tab."""
    out: Dict[str, Dict[str, Any]] = {}
    for bid, m in (index.get("models") or {}).items():
        out[bid] = {job: {"engines": j.get("engines") or [],
                          "matrix": j.get("matrix") or {}}
                    for job, j in (m.get("jobs") or {}).items()}
    return out


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

            def num(v):
                return f"{v:.4g}" if isinstance(v, (int, float)) else ""
            pbg_s = num(pbg) or "—"
            self_s = num(self_n) or "—"
            rows.append(
                f'<tr class="ov-row" data-kind="{kind}" '
                f'data-pbg="{pbg if isinstance(pbg,(int,float)) else -1}" '
                f'data-self="{self_n if isinstance(self_n,(int,float)) else -1}" '
                f'onclick="openModel(this,\'{bid}\')" style="cursor:pointer;">'
                f'<td>{bid}</td><td>{job}</td>'
                f'<td><span class="kind-tag">{kind}</span></td>'
                f'<td><span class="dot" style="background:{color}"></span>{label}</td>'
                f'<td class="num">{pbg_s}</td><td class="num">{self_s}</td>'
                f'<td class="num">{j.get("n_ok",0)}</td>'
                f'<td class="num">{j.get("n_failed",0)}</td></tr>'
                f'<tr class="detail-row" style="display:none;"><td colspan="8">'
                f'<div class="detail" id="detail-{bid}"></div></td></tr>'
            )
    return "".join(rows)


def _page(index: Dict[str, Any]) -> str:
    meta = index.get("meta") or {}
    n = len(index.get("models") or {})
    crashed = meta.get("crashed_models") or []
    cross = bco._cross_engine_tab_html(_index_to_comparisons(index),
                                       list((index.get("models") or {}).keys()))
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
</style></head><body>
<h3>BioModels batch comparison — {n} models{' · '+str(len(crashed))+' crashed' if crashed else ''}</h3>
<div>
 <button class="tab active" onclick="showTab(event,'overview')">Overview</button>
 <button class="tab" onclick="showTab(event,'cross')">Cross-engine</button>
</div>
<div id="overview" class="pane active">
 <div class="controls">Kind:
  <select id="kindFilter" onchange="applyFilter()">
   <option value="all">all</option><option value="utc">utc</option>
   <option value="steady_state">steady_state</option>
  </select>
  &nbsp;<span id="count"></span></div>
 <table id="ovtable"><thead><tr>
  <th onclick="sortBy(0,'s')">Biomodel</th><th onclick="sortBy(1,'s')">Job</th>
  <th onclick="sortBy(2,'s')">Kind</th><th>Status (pbg↔pbg)</th>
  <th class="num" onclick="sortBy(4,'pbg')">pbg↔pbg</th>
  <th class="num" onclick="sortBy(5,'self')">pbg↔ref</th>
  <th class="num" onclick="sortBy(6,'s')">OK</th>
  <th class="num" onclick="sortBy(7,'s')">failed</th>
 </tr></thead><tbody id="ovbody">{_overview_rows(index)}</tbody></table>
</div>
<div id="cross" class="pane">{cross}</div>
<script>{get_plotlyjs()}</script>
<script>
function showTab(e,id){{document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
 e.target.classList.add('active');
 document.querySelectorAll('.pane').forEach(p=>p.classList.remove('active'));
 document.getElementById(id).classList.add('active');}}
function applyFilter(){{var k=document.getElementById('kindFilter').value,c=0;
 document.querySelectorAll('#ovbody .ov-row').forEach(function(r){{
  var show=(k==='all'||r.dataset.kind===k);
  r.style.display=show?'':'none';
  r.nextElementSibling.style.display='none';
  if(show)c++;}});
 document.getElementById('count').textContent=c+' rows';}}
function sortBy(col,type){{var body=document.getElementById('ovbody');
 var rows=Array.from(body.querySelectorAll('.ov-row'));
 rows.sort(function(a,b){{
  if(type==='pbg'||type==='self'){{return parseFloat(b.dataset[type])-parseFloat(a.dataset[type]);}}
  return a.children[col].textContent.localeCompare(b.children[col].textContent);}});
 rows.forEach(function(r){{body.appendChild(r);body.appendChild(r.nextElementSibling);}});}}
function openModel(row,bid){{var d=row.nextElementSibling;
 var open=d.style.display!=='none';d.style.display=open?'none':'';
 if(open)return;
 var box=document.getElementById('detail-'+bid);
 if(box.dataset.loaded)return; box.textContent='loading…';
 fetch('/api/jobs/'+bid).then(r=>r.json()).then(function(jobs){{
  box.innerHTML=''; box.dataset.loaded='1';
  jobs.forEach(function(job){{var div=document.createElement('div');
   div.id='plot-'+bid+'-'+job; box.appendChild(div);
   fetch('/api/figure/'+bid+'?job='+encodeURIComponent(job)).then(r=>r.json())
    .then(function(fig){{Plotly.newPlot(div.id,fig.data,fig.layout,{{responsive:true,displaylogo:false}});}});}});}});}}
applyFilter();
</script></body></html>"""


def make_handler(out_dir: Path):
    index = _load_index(out_dir)

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
                if p.startswith("/api/figure/"):
                    bid = p.rsplit("/", 1)[-1]
                    job = (parse_qs(u.query).get("job") or [""])[0]
                    return self._send(json.dumps(_figure_for(out_dir, bid, job)))
                self.send_error(404)
            except Exception as e:  # don't kill the server on a bad model
                self.send_error(500, str(e))

    return H


def serve(out_dir: str, port: int = 8900) -> None:
    od = Path(out_dir)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(od))
    print(f"Lazy viewer for {od} → http://127.0.0.1:{port}  (Ctrl-C to stop)")
    httpd.serve_forever()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--port", type=int, default=8900)
    a = ap.parse_args()
    serve(a.out_dir, a.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
