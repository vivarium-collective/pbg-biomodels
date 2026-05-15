"""Composite document builders for the biomodels workspace.

Each module imported here fires its ``@composite_generator`` decorator on
package import, registering the generator with
``pbg_superpowers.composite_generator._REGISTRY``.
"""
from pbg_biomodels.composites import compare_biomodel  # noqa: F401
