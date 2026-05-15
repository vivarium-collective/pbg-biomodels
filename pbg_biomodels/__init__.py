"""pbg_biomodels — workspace Python package.

Importing the package fires the ``@composite_generator`` decorators inside
``composites/`` so ``discover_generators()`` finds them without callers
having to import each generator module explicitly.
"""
from pbg_biomodels import composites  # noqa: F401
