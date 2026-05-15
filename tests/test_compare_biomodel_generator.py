"""Generator-form of compare-biomodel: registers with the right shape and
fans out per-biomodel branches for arbitrary id lists."""
import pytest

# Import side-effect: fires the @composite_generator decorator and registers
# the entry in pbg_superpowers.composite_generator._REGISTRY.
import pbg_biomodels.composites.compare_biomodel  # noqa: F401
from pbg_superpowers.composite_generator import _REGISTRY, build_generator


def _entry():
    matches = [e for e in _REGISTRY.values() if e.name == "compare-biomodel"]
    assert len(matches) == 1, f"expected 1 generator named 'compare-biomodel', got {len(matches)}"
    return matches[0]


def test_generator_is_registered_with_list_param():
    """The generator exposes biomodel_ids as a list[string] parameter."""
    entry = _entry()
    assert "biomodel_ids" in entry.parameters
    pdef = entry.parameters["biomodel_ids"]
    assert pdef["type"] == "list[string]"
    assert isinstance(pdef.get("default"), list)
    assert pdef["default"] and all(isinstance(x, str) for x in pdef["default"])


def test_build_fans_out_per_biomodel_steps():
    """Two biomodels → two full step quartets + one shared multi-viz."""
    doc = build_generator(_entry(), overrides={
        "biomodel_ids": ["BIOMD0000000001", "BIOMD0000000005"],
    })
    state = doc["state"] if "state" in doc else doc

    # One quartet of Steps per biomodel id (top-level keys, suffixed by id).
    for bid in ("BIOMD0000000001", "BIOMD0000000005"):
        for stem in ("load", "copasi_step", "tellurium_step", "compare"):
            key = f"{stem}_{bid}"
            assert key in state, f"missing step {key!r}"
            assert state[key]["_type"] == "step"
        # Per-biomodel data stores (flat top-level, suffixed by id).
        for store in ("sbml_path", "sim_time", "n_points",
                      "copasi", "tellurium", "comparison"):
            assert f"{store}_{bid}" in state, f"missing store {store}_{bid}"

    # Per-id compare step wires into THAT biomodel's stores.
    cmp_step = state["compare_BIOMD0000000001"]
    assert cmp_step["inputs"]["engine_a_result"] == ["copasi_BIOMD0000000001"]
    assert cmp_step["inputs"]["engine_b_result"] == ["tellurium_BIOMD0000000001"]
    assert cmp_step["outputs"]["comparison"] == ["comparison_BIOMD0000000001"]

    # One multi-viz step carrying biomodel_ids in its config so the
    # CompareOverlay can declare per-biomodel input ports dynamically.
    viz = state["multi_overlay_viz"]
    assert viz["_type"] == "step"
    assert viz["address"].endswith("CompareOverlay")
    assert set(viz["config"]["biomodel_ids"]) == {"BIOMD0000000001", "BIOMD0000000005"}
    # Every per-biomodel triplet wired as a viz input port.
    for bid in ("BIOMD0000000001", "BIOMD0000000005"):
        for port in (f"copasi_{bid}", f"tellurium_{bid}", f"comparison_{bid}"):
            assert port in viz["inputs"]


def test_unknown_override_raises():
    """build_generator rejects override keys the function doesn't declare."""
    with pytest.raises(ValueError, match="unknown parameter"):
        build_generator(_entry(), overrides={"biomodel_id": "BIOMD0000000001"})
