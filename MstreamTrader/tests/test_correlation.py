"""
Tests pytest : Matrice de corrélation Pearson.
"""

import pytest
import random
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.correlation import (
    pearson_correlation, compute_correlation_matrix,
    get_correlation, is_too_correlated, diversification_score,
)


def test_pearson_perfect_positive():
    """y = 2x → corrélation = +1.0."""
    x = list(range(100))
    y = [2 * v for v in x]
    r = pearson_correlation(x, y)
    assert abs(r - 1.0) < 1e-9


def test_pearson_perfect_negative():
    """y = -x → corrélation = -1.0."""
    x = list(range(100))
    y = [-v for v in x]
    r = pearson_correlation(x, y)
    assert abs(r - (-1.0)) < 1e-9


def test_pearson_zero_variance_returns_none():
    """Si x ou y constant → variance nulle → None."""
    assert pearson_correlation([1] * 100, list(range(100))) is None
    assert pearson_correlation(list(range(100)), [5] * 100) is None


def test_pearson_small_sample_returns_none():
    """N < 10 → pas de confiance, None."""
    assert pearson_correlation([1, 2, 3], [2, 4, 6]) is None


def test_compute_correlation_matrix_symmetric_keys():
    """La clé (A, B) est triée alphabétiquement."""
    candles_a = [{"timestamp": i, "close": 100 + i} for i in range(50)]
    candles_b = [{"timestamp": i, "close": 50 + i*2} for i in range(50)]
    m = compute_correlation_matrix({"bitcoin": candles_a, "ethereum": candles_b})
    # La clé doit être ("bitcoin", "ethereum"), pas ("ethereum", "bitcoin")
    assert ("bitcoin", "ethereum") in m
    assert ("ethereum", "bitcoin") not in m


def test_get_correlation_bidirectional():
    """get_correlation(A, B) == get_correlation(B, A)."""
    matrix = {("a", "b"): 0.75}
    assert get_correlation(matrix, "a", "b") == 0.75
    assert get_correlation(matrix, "b", "a") == 0.75
    assert get_correlation(matrix, "a", "a") == 1.0


def test_is_too_correlated_blocks_correctly():
    """Seuil 0.70 : corr=0.80 bloqué, corr=0.60 accepté."""
    # IMPORTANT : la matrice utilise des clés triées alphabétiquement
    # (convention de compute_correlation_matrix)
    matrix = {
        tuple(sorted(["new_coin", "held_1"])): 0.80,   # ("held_1", "new_coin")
        tuple(sorted(["new_coin", "held_2"])): 0.40,   # ("held_2", "new_coin")
    }
    too, offender, val = is_too_correlated(
        matrix, "new_coin", {"held_1", "held_2"}, threshold=0.70
    )
    assert too is True
    assert offender == "held_1"
    assert val == 0.80

    # Avec un seuil plus haut, même coin pas bloqué
    too2, _, _ = is_too_correlated(
        matrix, "new_coin", {"held_1", "held_2"}, threshold=0.90
    )
    assert too2 is False


def test_diversification_score_uncorrelated():
    """Coins décorrélés → score proche de 1."""
    matrix = {("a", "b"): 0.0, ("a", "c"): 0.0, ("b", "c"): 0.0}
    s = diversification_score(matrix, ["a", "b", "c"])
    assert abs(s - 1.0) < 1e-9


def test_diversification_score_perfectly_correlated():
    """Coins parfaitement corrélés → score proche de 0."""
    matrix = {("a", "b"): 1.0, ("a", "c"): 1.0, ("b", "c"): 1.0}
    s = diversification_score(matrix, ["a", "b", "c"])
    assert abs(s - 0.0) < 1e-9
