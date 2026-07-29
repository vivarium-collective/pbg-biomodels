"""viva_biomodels — workspace Python package.

Importing the package fires the ``@composite_generator`` decorators inside
``composites/`` so ``discover_generators()`` finds them without callers
having to import each generator module explicitly.

Also provides the shared bigraph-schema type dictionaries absorbed from
viva-biomodels-bundle (register_types, TYPES_DICT) and re-exports the
public Steps so callers can do ``from viva_biomodels import SimulatorComparisonStep``.
"""
from viva_biomodels import composites  # noqa: F401

# ---------------------------------------------------------------------------
# Shared bigraph-schema type registrations (absorbed from viva-biomodels-bundle)
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


from viva_biomodels.types import register_simulation_types  # noqa: E402


def register_types(core):
    """Register viva-biomodels bigraph-schema types into a ProcessBigraph core."""
    core.register_types(TYPES_DICT)
    register_simulation_types(core)
    return core


# Re-export the public Step so callers can do
# `from viva_biomodels import SimulatorComparisonStep`.
# Imported here (not at the top) so that `register_types` keeps working even
# when downstream dependencies of the steps subpackage are missing.
from viva_biomodels.steps import SimulatorComparisonStep  # noqa: E402

__all__ = ["TYPES_DICT", "register_types", "SimulatorComparisonStep"]
