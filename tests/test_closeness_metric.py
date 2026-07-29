"""BioSimulations closeness-score metric — faithful to Lucian's
biosimulations_runutils hdf5_compare.compare_arrays.
"""
import numpy as np

from viva_biomodels.comparison import closeness_score, closeness_bucket_for


def test_identical_series_is_close_zero():
    assert closeness_score([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == (True, 0.0)


def test_matches_numpy_allclose_verdict():
    a = [1.0, 2.0, 3.0]
    b = [1.0, 2.0, 3.05]
    close, score = closeness_score(a, b)
    atol = max(1e-3, max(map(abs, a)) * 1e-5, max(map(abs, b)) * 1e-5)
    assert close == bool(np.allclose(a, b, rtol=1e-4, atol=atol))
    assert (score <= 1.0) == close


def test_large_deviation_not_close():
    close, score = closeness_score([1.0, 2.0], [1.0, 5.0])
    assert close is False and score > 1.0


def test_nan_returns_sentinel():
    assert closeness_score([1.0, float("nan")], [1.0, 2.0]) == (False, 1e10)


def test_empty_series_is_close():
    assert closeness_score([], []) == (True, 0.0)


def test_bucket_mapping():
    assert closeness_bucket_for(0.0)[0] == "close"
    assert closeness_bucket_for(5.0)[0] == "not_close"
    assert closeness_bucket_for(1e10)[0] == "error"
    assert closeness_bucket_for(None) == closeness_bucket_for(None)
