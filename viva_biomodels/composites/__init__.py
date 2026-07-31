"""Composite document builders for the biomodels workspace.

Each module imported here fires its ``@composite_generator`` decorator on
package import, registering the generator with
``viva_superpowers.composite_generator._REGISTRY``.
"""
from viva_biomodels.composites import batch_compare_biomodels  # noqa: F401
from viva_biomodels.composites import biomodel_process  # noqa: F401
from viva_biomodels.composites import compare_biomodel  # noqa: F401
from viva_biomodels.composites import compare_simulators  # noqa: F401
