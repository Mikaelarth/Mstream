"""
MstreamTrader - Dynamic Correlation Matrix
============================================

Le piège #1 de la diversification crypto : croire que détenir BTC + ETH + BNB + SOL
diversifie le risque. FAUX. Sur 24h, ces coins sont corrélés à 85-95 %.

Ce module calcule la matrice de corrélation glissante sur N jours et permet
au bot de REFUSER d'ouvrir une position si elle est trop corrélée avec
une position déjà ouverte.

Méthode :
    - Pearson correlation sur les RETURNS (pas les prix absolus)
    - Rolling window : 30 jours par défaut
    - Mise à jour à chaque cycle

Seuil de blocage :
    > 0.75 = haute corrélation → blocage
    [0.50, 0.75] = corrélation modérée → avertissement
    < 0.50 = diversification réelle

Pure Python — pas de numpy pour compat Android.
"""

import math
from typing import Optional


def _compute_returns(candles: list[dict]) -> list[float]:
    """Transforme une liste de bougies en liste de retours simples (close à close)."""
    if not candles or len(candles) < 2:
        return []
    closes = [c.get("close", 0) for c in candles if c.get("close", 0) > 0]
    returns = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev > 0:
            returns.append((closes[i] - prev) / prev)
    return returns


def pearson_correlation(x: list[float], y: list[float]) -> Optional[float]:
    """
    Corrélation de Pearson entre deux séries de même longueur.
    Retourne None si non calculable (variance nulle, séries vides).
    """
    n = min(len(x), len(y))
    if n < 10:   # échantillon trop petit = peu fiable
        return None

    # Tronquer à la même longueur (si décalage)
    x = x[-n:]
    y = y[-n:]

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    cov     = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / n
    var_x   = sum((xi - mean_x) ** 2 for xi in x) / n
    var_y   = sum((yi - mean_y) ** 2 for yi in y) / n

    if var_x <= 0 or var_y <= 0:
        return None
    return cov / math.sqrt(var_x * var_y)


def compute_correlation_matrix(coins_data: dict,
                                 lookback_candles: Optional[int] = None) -> dict:
    """
    Calcule la matrice de corrélation entre tous les coins fournis.

    Args:
        coins_data       : dict[coin_id → list[candles]]
        lookback_candles : nombre de bougies à utiliser (None = toutes)

    Retourne un dict de la forme :
        {
            ("bitcoin", "ethereum"):  0.872,
            ("bitcoin", "solana"):    0.815,
            ("ethereum", "solana"):   0.790,
            ...
        }
    La clé est triée alphabétiquement (pas de doublons).
    """
    # Calculer les returns pour chaque coin
    returns_by_coin = {}
    for cid, candles in coins_data.items():
        if lookback_candles:
            candles = candles[-lookback_candles:]
        returns = _compute_returns(candles)
        if returns and len(returns) >= 10:
            returns_by_coin[cid] = returns

    # Matrice symétrique (on stocke seulement un triangle)
    matrix = {}
    coins = sorted(returns_by_coin.keys())
    for i, c1 in enumerate(coins):
        for c2 in coins[i + 1:]:
            corr = pearson_correlation(returns_by_coin[c1], returns_by_coin[c2])
            if corr is not None:
                key = tuple(sorted([c1, c2]))
                matrix[key] = corr
    return matrix


def get_correlation(matrix: dict, coin1: str, coin2: str) -> Optional[float]:
    """Lookup de corrélation (retourne None si non présente)."""
    if coin1 == coin2:
        return 1.0
    return matrix.get(tuple(sorted([coin1, coin2])))


def is_too_correlated(matrix: dict, new_coin: str, held_coins: set,
                       threshold: float = 0.75) -> tuple[bool, Optional[str], float]:
    """
    Vérifie si `new_coin` est trop corrélé avec l'une des positions déjà ouvertes.

    Retourne:
        (too_correlated, offending_coin, max_correlation)
    """
    if not held_coins:
        return False, None, 0.0

    max_corr = 0.0
    offender = None
    for held in held_coins:
        if held == new_coin:
            continue
        corr = get_correlation(matrix, new_coin, held)
        if corr is None:
            continue
        if abs(corr) > abs(max_corr):
            max_corr = corr
            offender = held

    return (abs(max_corr) >= threshold), offender, max_corr


def diversification_score(matrix: dict, coins_in_portfolio: list) -> float:
    """
    Score de diversification du portefeuille :
        1.0 = parfaitement diversifié (toutes corrélations = 0)
        0.0 = tout est parfaitement corrélé (une seule "vraie" position)

    Calculé comme : 1 − moyenne des |corr| entre paires.
    """
    if len(coins_in_portfolio) < 2:
        return 1.0

    correlations = []
    for i, c1 in enumerate(coins_in_portfolio):
        for c2 in coins_in_portfolio[i + 1:]:
            corr = get_correlation(matrix, c1, c2)
            if corr is not None:
                correlations.append(abs(corr))

    if not correlations:
        return 1.0
    return 1.0 - (sum(correlations) / len(correlations))


def correlation_clusters(matrix: dict, all_coins: list,
                          threshold: float = 0.70) -> list[list[str]]:
    """
    Groupe les coins par clusters de haute corrélation.
    Algorithme simple (pas k-means, juste union-find).

    Retourne une liste de clusters : [[btc, eth, bnb], [xrp], [ada, dot], ...]
    Utile pour l'analyse : "ces coins sont en réalité un seul pari".
    """
    # Union-Find
    parent = {c: c for c in all_coins}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for (c1, c2), corr in matrix.items():
        if c1 in parent and c2 in parent and abs(corr) >= threshold:
            union(c1, c2)

    clusters_by_root = {}
    for c in all_coins:
        root = find(c)
        clusters_by_root.setdefault(root, []).append(c)

    return [sorted(cluster) for cluster in clusters_by_root.values()]


def format_matrix_text(matrix: dict, coins: list) -> str:
    """Format lisible pour debug / audit."""
    lines = ["Matrice de correlation:"]
    header = "          " + "  ".join(f"{c[:6]:>6}" for c in coins)
    lines.append(header)
    for c1 in coins:
        row = [f"{c1[:6]:>8}"]
        for c2 in coins:
            if c1 == c2:
                row.append("  1.00")
            else:
                corr = get_correlation(matrix, c1, c2)
                row.append(f"{corr:>6.2f}" if corr is not None else "     -")
        lines.append("  " + "  ".join(row))
    return "\n".join(lines)
