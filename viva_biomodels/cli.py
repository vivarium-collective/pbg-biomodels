"""``pbg-biomodels`` command-line interface.

Subcommands:

* ``compare`` — run one or more BioModels under a set of simulators (and any
  external reference CSVs), score every pair with an nRMSE matrix, and write a
  navigable HTML report.
* ``process`` — emit a composite document with a single BioModel loaded into one
  simulator's time-coupled process (a pluggable module); optionally run it.

Examples::

    pbg-biomodels compare BIOMD0000000001 BIOMD0000000012
    pbg-biomodels compare BIOMD0000000001 --simulators copasi,simbio
    pbg-biomodels compare BIOMD0000000001 \\
        --reference BIOMD0000000001=experiment.csv --out report.html
    pbg-biomodels process BIOMD0000000001 --simulator simbio --out module.json
    pbg-biomodels process BIOMD0000000001 --simulator simbio --run 20
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Dict, List, Optional


def _parse_references(items: Optional[List[str]]) -> Dict[str, Dict[str, str]]:
    """Parse ``--reference`` values into ``{biomodel_id: {name: path}}``.

    Accepted forms (repeatable):
        BIOMD...=path.csv            -> reference name defaults to "reference"
        BIOMD...:label=path.csv      -> reference name is "label"
    """
    refs: Dict[str, Dict[str, str]] = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(
                f"--reference expects BIOMODEL_ID[:name]=path.csv, got {item!r}"
            )
        left, path = item.split("=", 1)
        if ":" in left:
            bid, name = left.split(":", 1)
        else:
            bid, name = left, "reference"
        refs.setdefault(bid.strip(), {})[name.strip()] = path.strip()
    return refs


def _cmd_compare(args: argparse.Namespace) -> int:
    from viva_biomodels.composites.compare_simulators import run_comparison
    from viva_biomodels.report import build_comparison_report
    from viva_biomodels.simulators import resolve_simulators

    sims = resolve_simulators(args.simulators)
    references = _parse_references(args.reference)

    print(f"Comparing {len(args.biomodels)} biomodel(s) under: {', '.join(sims)}")
    if references:
        print(f"Reference datasets: {references}")

    def _progress(bid, status):
        print(f"  {bid}: {status}")

    results = run_comparison(
        args.biomodels, simulators=sims, references=references, on_progress=_progress
    )

    n_ok = sum(1 for b in results.values() if not b.get("error"))
    print(f"{n_ok}/{len(results)} biomodel(s) completed.")
    out = build_comparison_report(results, args.out, title=args.title)
    print(f"Report written to {out}")
    if args.open:
        import webbrowser
        webbrowser.open(f"file://{out.resolve()}")
    return 0


def _cmd_process(args: argparse.Namespace) -> int:
    from viva_biomodels.composites.biomodel_process import (
        build_biomodel_process_document,
    )

    doc = build_biomodel_process_document(
        args.biomodel, args.simulator, interval=args.interval
    )

    if args.run:
        from process_bigraph import Composite, gather_emitter_results

        from viva_biomodels import register_types
        from viva_biomodels.core import build_core

        composite = Composite(doc, core=register_types(build_core()))
        composite.run(args.run * args.interval)
        rows = gather_emitter_results(composite).get(("emitter",), [])
        last = rows[-1] if rows else {}
        print(f"Ran {args.simulator} on {args.biomodel} for {args.run} step(s); "
              f"final t={last.get('time')}, {len(last.get('species', {}))} species")
        species = last.get("species", {})
        for name in list(species)[:10]:
            print(f"    {name} = {species[name]:.4g}")
        return 0

    text = json.dumps(doc, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"Composite document written to {args.out}")
    else:
        print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    from viva_biomodels.simulators import ALL_SIMULATORS

    parser = argparse.ArgumentParser(
        prog="pbg-biomodels",
        description="Compare BioModels across simulators and build pluggable processes.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    c = sub.add_parser("compare", help="Run a multi-simulator comparison + HTML report.")
    c.add_argument("biomodels", nargs="+", help="BioModels identifiers.")
    c.add_argument("--simulators", default="all",
                   help=f"'all' or comma-separated subset of {ALL_SIMULATORS}.")
    c.add_argument("--reference", action="append", metavar="BIOMODEL[:name]=path.csv",
                   help="External reference CSV, scored as an engine (repeatable).")
    c.add_argument("--out", default="comparison_report.html",
                   help="Output HTML path (default: comparison_report.html).")
    c.add_argument("--title", default="BioModels simulator comparison",
                   help="Report title.")
    c.add_argument("--open", action="store_true", help="Open the report in a browser.")
    c.set_defaults(func=_cmd_compare)

    p = sub.add_parser("process", help="Emit/run a single BioModel-in-one-simulator process.")
    p.add_argument("biomodel", help="BioModels identifier.")
    p.add_argument("--simulator", default="simbio",
                   help=f"One of {ALL_SIMULATORS} (default: simbio).")
    p.add_argument("--interval", type=float, default=1.0, help="Process tick size.")
    p.add_argument("--run", type=int, metavar="N",
                   help="Run N steps and print a summary instead of dumping the doc.")
    p.add_argument("--out", help="Write the composite document JSON to this path.")
    p.set_defaults(func=_cmd_process)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
