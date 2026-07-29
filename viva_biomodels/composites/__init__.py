"""Composite document builders for the biomodels workspace.

Each module imported here fires its ``@composite_generator`` decorator on
package import, registering the generator with
``viva_superpowers.composite_generator._REGISTRY``.
"""
import dataclasses as _dataclasses

from viva_superpowers.composite_generator import _REGISTRY as _COMPOSITE_REGISTRY

from viva_biomodels.composites import batch_compare_biomodels  # noqa: F401
from viva_biomodels.composites import biomodel_process  # noqa: F401
from viva_biomodels.composites import compare_biomodel  # noqa: F401
from viva_biomodels.composites import compare_simulators  # noqa: F401


# --- Clean module-path aliases ---------------------------------------------
# A generator ids as ``{module}.{name}`` — e.g.
# ``viva_biomodels.composites.batch_compare_biomodels.batch-compare-biomodels``.
# The hyphenated tail fails the workbench study-schema's composite-path regex
# (^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$), so a study can't reference it. Register
# a clean alias per generator = the id minus its trailing name segment
# (``viva_biomodels.composites.batch_compare_biomodels``), which is regex-valid
# and resolves to the same generator. Aliases share the entry's ``func`` so
# ``build_composite`` dedupes them by function identity.
def _register_module_aliases() -> None:
    for key, entry in list(_COMPOSITE_REGISTRY.items()):
        if not str(key).startswith("viva_biomodels.composites."):
            continue
        clean = str(key).rsplit(".", 1)[0]  # drop the trailing generator name
        if clean != key and clean not in _COMPOSITE_REGISTRY:
            _COMPOSITE_REGISTRY[clean] = _dataclasses.replace(entry, id=clean)


_register_module_aliases()
