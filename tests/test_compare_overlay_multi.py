"""CompareOverlay renders a summary-card grid for N biomodels, each card
collapsible to its species small-multiples."""
from pbg_biomodels.core import build_core
from pbg_biomodels.visualizations.compare_overlay import CompareOverlay, _build_figure


def _overlay(biomodel_ids):
    """Construct a CompareOverlay configured for the given biomodel ids."""
    return CompareOverlay(
        {"title": "", "biomodel_ids": list(biomodel_ids)},
        core=build_core(),
    )


def _state_for(biomodel_specs):
    """Build the flat input-port state the runtime would deliver.

    biomodel_specs: dict of ``{biomodel_id: {bucket, label, mean, n_shared}}``
    """
    state = {}
    for bid, spec in biomodel_specs.items():
        state[f"copasi_{bid}"] = {
            "time": [0.0, 1.0],
            "columns": ["S1", "S2"],
            "values": [[1.0, 2.0], [1.1, 2.1]],
        }
        state[f"tellurium_{bid}"] = {
            "time": [0.0, 1.0],
            "columns": ["S1", "S2"],
            "values": [[1.01, 2.01], [1.11, 2.11]],
        }
        state[f"comparison_{bid}"] = {
            "n_shared":         spec.get("n_shared", 2),
            "rmse_by_species":  {"S1": 0.01, "S2": 0.01},
            "nrmse_by_species": {"S1": 0.04, "S2": 0.02},
            "mean_nrmse":       spec.get("mean", 0.04),
            "bucket":           spec.get("bucket", "good"),
            "bucket_label":     spec.get("label", "good match"),
        }
    return state


def test_renders_one_summary_card_per_biomodel():
    """N biomodels → N cards, each labelled with its id and bucket."""
    ids = ["BIOMD0000000001", "BIOMD0000000005"]
    overlay = _overlay(ids)
    out = overlay.update(_state_for({
        "BIOMD0000000001": {"bucket": "good",       "label": "good match"},
        "BIOMD0000000005": {"bucket": "borderline", "label": "borderline", "mean": 0.18},
    }))
    html = out["html"]
    assert "BIOMD0000000001" in html
    assert "BIOMD0000000005" in html
    assert "good match" in html
    assert "borderline" in html


def test_clicking_a_card_toggles_its_section():
    """Cards carry a data-biomodel hook; matching detail panes start hidden;
    the embedded JS wires click→toggle."""
    bid = "BIOMD0000000001"
    overlay = _overlay([bid])
    out = overlay.update(_state_for({bid: {}}))
    html = out["html"]
    assert f'data-biomodel="{bid}"' in html
    assert f'id="detail-{bid}"' in html
    assert "data-biomodel" in html and "addEventListener" in html


def test_empty_biomodel_ids_does_not_crash():
    """Configured with no ids → an empty-state HTML, not an exception."""
    overlay = _overlay([])
    out = overlay.update({})
    assert isinstance(out, dict) and isinstance(out.get("html"), str)


def test_engine_colors_consistent_across_subplots():
    """All COPASI traces share one color across species subplots; all
    Tellurium traces share another. Plotly's auto-cycle would otherwise
    drift because traces are interleaved per-species (engine_a, engine_b,
    engine_a, engine_b, …)."""
    a_series = {"S1": [1.0, 2.0], "S2": [3.0, 4.0], "S3": [5.0, 6.0]}
    b_series = {"S1": [1.1, 2.1], "S2": [3.1, 4.1], "S3": [5.1, 6.1]}
    fig = _build_figure(a_series, [0.0, 1.0], "COPASI",
                        b_series, [0.0, 1.0], "Tellurium")
    copasi_colors = {t["line"]["color"] for t in fig["data"] if t["name"] == "COPASI"}
    tellurium_colors = {t["line"]["color"] for t in fig["data"] if t["name"] == "Tellurium"}
    assert len(copasi_colors) == 1, f"COPASI colors drift: {copasi_colors}"
    assert len(tellurium_colors) == 1, f"Tellurium colors drift: {tellurium_colors}"
    assert copasi_colors != tellurium_colors, "engines must visibly differ"
