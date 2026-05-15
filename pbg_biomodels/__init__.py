"""pbg_biomodels — workspace Python package.

Importing the package fires the ``@composite_generator`` decorators inside
``composites/`` so ``discover_generators()`` finds them without callers
having to import each generator module explicitly.

Also provides the shared bigraph-schema type dictionaries absorbed from
pbg-biomodels-bundle (register_types, TYPES_DICT) and re-exports the
public Steps so callers can do ``from pbg_biomodels import SimulatorComparisonStep``.
"""
from pbg_biomodels import composites  # noqa: F401

# ---------------------------------------------------------------------------
# Shared bigraph-schema type registrations (absorbed from pbg-biomodels-bundle)
# ---------------------------------------------------------------------------

sed_types = {
    'result': {
        'time': 'list[float]',
        'species_concentrations': 'map[list[float]]',
    },
    'results': 'map[result]'
}

standard_types = {
    'numeric_result': {
        'time': 'list[float]',
        'columns': 'list[string]',
        'values': 'list[list[float]]',
    },
    'numeric_results': 'map[numeric_result]',
    'columns_of_interest': 'list[string]'
}

TYPES_DICT = {
    **standard_types,
    **sed_types
}


def register_types(core):
    """Register pbg-biomodels bigraph-schema types into a ProcessBigraph core."""
    core.register_types(TYPES_DICT)
    return core


# Re-export the public Step so callers can do
# `from pbg_biomodels import SimulatorComparisonStep`.
# Imported here (not at the top) so that `register_types` keeps working even
# when downstream dependencies of the steps subpackage are missing.
from pbg_biomodels.steps import SimulatorComparisonStep  # noqa: E402

__all__ = ["TYPES_DICT", "register_types", "SimulatorComparisonStep"]
