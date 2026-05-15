"""build_core() — wraps process_bigraph.allocate_core() + workspace-local Edges.

allocate_core() auto-discovers Processes/Steps from installed pbg-* packages
via bigraph-schema's dist-walker. Workspace-local code lives in
``pbg_biomodels/`` but the workspace is intentionally NOT a distributable
wheel (``[tool.hatch.build.targets.wheel] bypass-selection = true``) — so
the dist-walker can't find workspace-local Edges.

To avoid manual registrations drifting out of date as the workspace grows,
``build_core`` walks the ``pbg_biomodels`` package for any ``Step`` /
``Process`` subclass defined locally (i.e., ``cls.__module__`` starts with
``pbg_biomodels.``) and registers each one twice — by full dotted path
(``pbg_biomodels.steps.X.Y``) and by short class name (``Y``). This
replicates what the dist-walker would have done for an installed wheel.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Iterable

from process_bigraph import Process, Step, allocate_core

import pbg_biomodels


def build_core():
    core = allocate_core()
    for cls, dotted in _iter_workspace_edges(pbg_biomodels):
        core.register_link(dotted, cls)
        core.register_link(cls.__name__, cls)
    return core


def _iter_workspace_edges(package) -> Iterable[tuple[type, str]]:
    """Yield (class, dotted_path) for every Step/Process subclass defined inside ``package``.

    Skips:
    - The ``Step`` / ``Process`` base classes themselves.
    - Re-exports (classes whose ``__module__`` doesn't start with the package's name —
      e.g. ``CopasiUTCStep`` imported into a wrapper module).
    - Modules that fail to import (logged via warning).
    """
    pkg_name = package.__name__
    seen: set[type] = set()
    for _, modname, _ in pkgutil.walk_packages(package.__path__, prefix=f"{pkg_name}."):
        try:
            mod = importlib.import_module(modname)
        except Exception as exc:
            import warnings
            warnings.warn(f"build_core: skipping {modname}: {type(exc).__name__}: {exc}")
            continue
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            if cls in (Step, Process):
                continue
            if not issubclass(cls, (Step, Process)):
                continue
            if not (cls.__module__ or "").startswith(pkg_name + "."):
                # Defined elsewhere (re-export) — owner package registers it.
                continue
            if cls in seen:
                continue
            seen.add(cls)
            yield cls, f"{cls.__module__}.{cls.__name__}"
