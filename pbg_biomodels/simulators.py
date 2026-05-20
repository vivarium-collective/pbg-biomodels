"""Registry of the simulator backends pbg-biomodels can compare.

Each entry maps a short name (used on the CLI and in composite wiring) to:

* ``utc_step``  — the adapter Step address that runs a one-shot uniform time
  course and emits the canonical ``numeric_result`` shape. Used by the
  compare-biomodel composite.
* ``process``   — the canonical time-coupled ``<Sim>UTCProcess`` address, used
  by the single pluggable-process composite.
* ``process_config(sbml_path)`` — builds that Process's config for a local SBML
  file (the per-simulator config keys differ).
* ``species_out`` — the Process output port carrying species concentrations
  (also differs per simulator).

Adding a new simulator backend is a single entry here.
"""
from __future__ import annotations

from typing import Callable, Dict, List, TypedDict


class SimulatorSpec(TypedDict):
    utc_step: str
    process: str
    process_config: Callable[[str], Dict[str, object]]
    species_out: str


_SIMULATORS: Dict[str, SimulatorSpec] = {
    "copasi": {
        "utc_step": "local:pbg_biomodels.steps.simulators.BiomodelsCopasiStep",
        "process": "local:CopasiUTCProcess",
        "process_config": lambda sbml: {
            "model_source": sbml,
            "time": 1.0,
            "intervals": 10,
        },
        "species_out": "species_concentrations",
    },
    "tellurium": {
        "utc_step": "local:pbg_biomodels.steps.simulators.BiomodelsTelluriumStep",
        "process": "local:TelluriumProcess",
        "process_config": lambda sbml: {"model_file": sbml},
        "species_out": "species",
    },
    "simbio": {
        "utc_step": "local:pbg_biomodels.steps.simulators.BiomodelsSimbioStep",
        "process": "local:SimbioUTCProcess",
        "process_config": lambda sbml: {"model_source": sbml, "model_format": "sbml"},
        "species_out": "species_concentrations",
    },
}

#: All known simulator names, in canonical order.
ALL_SIMULATORS: List[str] = list(_SIMULATORS)


def resolve_simulators(spec) -> List[str]:
    """Normalize a simulator selection to a validated list of names.

    Accepts ``None`` / ``"all"`` / ``["all"]`` (→ every simulator), a
    comma-separated string, or an iterable of names. Raises ``ValueError`` on
    an unknown name.
    """
    if spec is None or spec == "all" or spec == ["all"]:
        return list(ALL_SIMULATORS)
    if isinstance(spec, str):
        names = [s.strip() for s in spec.split(",") if s.strip()]
    else:
        names = [str(s).strip() for s in spec if str(s).strip()]
    if names == ["all"]:
        return list(ALL_SIMULATORS)
    unknown = [n for n in names if n not in _SIMULATORS]
    if unknown:
        raise ValueError(
            f"Unknown simulator(s) {unknown}; known: {ALL_SIMULATORS}"
        )
    if not names:
        raise ValueError("No simulators selected.")
    return names


# Canonical Process classes, by simulator name → (module, class). Registered
# explicitly because pbg-simbio is installed editable (hatchling editable
# installs omit top_level.txt, so bigraph-schema's dist-walker can't discover
# its Edges); registering here keeps `local:<Sim>UTCProcess` resolvable.
_PROCESS_CLASSES = {
    "copasi": ("pbg_copasi.processes", "CopasiUTCProcess"),
    "tellurium": ("pbg_tellurium.processes", "TelluriumProcess"),
    "simbio": ("pbg_simbio.processes", "SimbioUTCProcess"),
}


def register_simulator_backends(core):
    """Register the canonical ``<Sim>UTCProcess`` classes under their names."""
    import importlib

    for module_name, class_name in _PROCESS_CLASSES.values():
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        cls = getattr(module, class_name, None)
        if cls is not None:
            core.register_link(class_name, cls)
    return core


def utc_step_address(name: str) -> str:
    return _SIMULATORS[name]["utc_step"]


def process_address(name: str) -> str:
    return _SIMULATORS[name]["process"]


def process_config(name: str, sbml_path: str) -> Dict[str, object]:
    return _SIMULATORS[name]["process_config"](sbml_path)


def species_output_port(name: str) -> str:
    return _SIMULATORS[name]["species_out"]
