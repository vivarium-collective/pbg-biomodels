"""build_core() — wraps process_bigraph.allocate_core() + workspace-local Edges.

allocate_core() auto-discovers Processes/Steps from installed pbg-* packages
via bigraph-schema's dist-walker. Workspace-local code lives in
``pbg_biomodels/`` but the workspace is intentionally NOT a distributable
wheel (``[tool.hatch.build.targets.wheel] bypass-selection = true``) — so
the dist-walker can't find workspace-local Edges. Anything we want to
expose to the Registry must be imported + registered explicitly here.
"""
from process_bigraph import allocate_core

from pbg_biomodels.visualizations.compare_overlay import CompareOverlay


def build_core():
    core = allocate_core()
    # Workspace-local Edges (not auto-discovered — see module docstring).
    core.register_link("pbg_biomodels.visualizations.compare_overlay.CompareOverlay", CompareOverlay)
    core.register_link("CompareOverlay", CompareOverlay)
    return core
