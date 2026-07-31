"""Single pluggable-process composite: a BioModel loaded into one simulator.

``build_biomodel_process_document(biomodel_id, simulator)`` resolves the
BioModel's SBML (cached under ``models/<id>/``) and returns a composite
document carrying exactly one canonical time-coupled ``<Sim>UTCProcess``
configured with that model — wired to a shared ``species`` store and a
RAM emitter. The document is meant to be dropped into a larger bigraph as a
ready-to-run module: the host can re-wire the process's species port to couple
it with other processes.

A thin ``@composite_generator`` (``biomodel-process``) exposes it to the
dashboard.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from viva_superpowers.composite_generator import composite_generator

from viva_biomodels.simulators import (
    process_address,
    process_config,
    resolve_simulators,
    species_output_port,
)


def _resolve_sbml(biomodel_id: str) -> Tuple[str, float]:
    """Fetch/cache a BioModel and return ``(sbml_path, utc_duration)``."""
    import os

    import biomodels

    from viva_biomodels.run_biomodels import load_biomodel

    meta = biomodels.get_metadata(biomodel_id)
    result = load_biomodel(biomodel_id, meta)
    return os.path.abspath(result.sbml_path), float(result.utc.duration)


def build_biomodel_process_document(
    biomodel_id: str,
    simulator: str,
    *,
    sbml_path: Optional[str] = None,
    interval: float = 1.0,
    with_emitter: bool = True,
    emitter_address: str = "local:RAMEmitter",
) -> Dict[str, Any]:
    """Build a composite with one ``<Sim>UTCProcess`` loaded with ``biomodel_id``.

    Args:
        biomodel_id: BioModels identifier.
        simulator: a single simulator name (copasi / tellurium / simbio).
        sbml_path: pre-resolved SBML path; if None it is fetched/cached.
        interval: process tick size.
        with_emitter: attach a RAMEmitter capturing species + global_time.

    Returns:
        ``{"state": ...}`` ready for ``process_bigraph.Composite``.
    """
    names = resolve_simulators(simulator)
    if len(names) != 1:
        raise ValueError(
            f"biomodel-process needs exactly one simulator, got {names}"
        )
    name = names[0]

    if sbml_path is None:
        sbml_path, _duration = _resolve_sbml(biomodel_id)

    port = species_output_port(name)  # input and output share this port name
    proc_key = f"{name}_process"

    state: Dict[str, Any] = {
        "species": {},
        "species_input": {},
        proc_key: {
            "_type": "process",
            "address": process_address(name),
            "config": process_config(name, sbml_path),
            "interval": interval,
            # Input and output are wired to SEPARATE stores. Some backends
            # (tellurium) use the same port name for the maybe[...] input and
            # the overwrite[...] output; wiring both to one store would fail to
            # resolve. ``species`` holds the produced trajectory (read by the
            # emitter); ``species_input`` is the coupling port a host bigraph
            # re-points to feed concentrations in (empty here → runs from the
            # loaded model).
            "inputs": {port: ["species_input"]},
            "outputs": {port: ["species"]},
        },
    }

    if with_emitter:
        state["emitter"] = {
            "_type": "step",
            "address": emitter_address,
            # `species` captured as a node so it works whether the process
            # writes map[float] (copasi) or overwrite[map[float]] (tellurium,
            # simbio); global_time is the simulation clock.
            "config": {"emit": {"species": "node", "time": "float"}},
            "inputs": {"species": ["species"], "time": ["global_time"]},
        }

    return {"state": state}


@composite_generator(
    name="biomodel-process",
    description=(
        "Load a single BioModel into one simulator's time-coupled process, "
        "wired to a species store — a ready-to-plug module for a larger bigraph."
    ),
    parameters={
        "biomodel_id": {
            "type": "string",
            "default": "BIOMD0000000001",
            "description": "BioModels identifier.",
        },
        "simulator": {
            "type": "string",
            "default": "simbio",
            "description": "Simulator backend: copasi, tellurium, or simbio.",
        },
        "interval": {
            "type": "float",
            "default": 1.0,
            "description": "Process tick size.",
        },
    },
    default_n_steps=10,
)
def build_biomodel_process(
    core: Any = None,
    *,
    biomodel_id: str = "BIOMD0000000001",
    simulator: str = "simbio",
    interval: float = 1.0,
) -> Dict[str, Any]:
    return build_biomodel_process_document(biomodel_id, simulator, interval=interval)
