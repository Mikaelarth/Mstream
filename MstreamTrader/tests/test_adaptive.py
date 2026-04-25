"""
Tests pytest : agent adaptatif (Thompson + UCB + Attribution).

Garantit qu'en conditions normales :
  - Thompson Beta converge vers la vraie win rate
  - Le bandit identifie la meilleure stratégie
  - UCB détecte le meilleur profil
  - L'attribution par votes est correcte (pas uniforme)
  - Thread-safety : pas de race condition sur _total_trades
"""

import pytest
import random
import threading
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.adaptive import (
    StrategyPosterior, StrategyBandit,
    ParameterTuner, PARAM_PROFILES,
    AdaptiveAgent, DEFAULT_ALPHA, DEFAULT_BETA,
)


# ─── Thompson Sampling : convergence mathématique ─────────────────────────────

def test_beta_prior_mean_is_half():
    """Prior Beta(1, 1) = distribution uniforme → mean = 0.5."""
    p = StrategyPosterior(strategy="x", regime="bull")
    assert abs(p.mean() - 0.5) < 1e-9


def test_beta_converges_to_true_winrate():
    """100 trades 70W/30L → posterior mean ≈ 0.70 (erreur < 5%)."""
    random.seed(42)
    p = StrategyPosterior(strategy="x", regime="bull")
    for i in range(100):
        win = i < 70
        p.update(win=win, decay_applied=False)
    assert abs(p.mean() - 0.70) < 0.05, f"Mean={p.mean()}, expected ~0.70"


def test_beta_sampling_matches_mean_on_average():
    """Moyenne de 1000 samples ≈ posterior mean."""
    random.seed(42)
    p = StrategyPosterior(strategy="x", regime="bull", alpha=10.0, beta=3.0)
    samples = [p.sample() for _ in range(1000)]
    sample_mean = sum(samples) / len(samples)
    assert abs(sample_mean - p.mean()) < 0.03


# ─── Bandit : différenciation des stratégies ──────────────────────────────────

def test_bandit_converges_to_best_strategy():
    """Parmi 3 stratégies avec WR 70/50/30, le bandit doit favoriser la 70."""
    random.seed(123)
    bandit = StrategyBandit(strategies=("A", "B", "C"))
    true_wr = {"A": 0.70, "B": 0.50, "C": 0.30}
    selections = {"A": 0, "B": 0, "C": 0}

    for _ in range(500):
        weights = bandit.sample_weights("bull")
        selected = max(weights, key=weights.get)
        selections[selected] += 1
        won = random.random() < true_wr[selected]
        bandit.update(selected, "bull", win=won)

    assert selections["A"] > selections["B"] > selections["C"], \
        f"Convergence mal ordonnée : {selections}"
    # A devrait recevoir > 60 % des sélections
    assert selections["A"] / 500 > 0.6


def test_bandit_posterior_means_ordered_correctly():
    """Les posteriors means doivent refléter le vrai WR."""
    random.seed(456)
    bandit = StrategyBandit(strategies=("A", "B"))
    # A : 80 wins / 20 losses
    for i in range(100):
        bandit.update("A", "bull", win=(i < 80))
    # B : 20 wins / 80 losses
    for i in range(100):
        bandit.update("B", "bull", win=(i < 20))
    means = bandit.get_posterior_means("bull")
    assert means["A"] > means["B"]
    assert means["A"] > 0.60
    assert means["B"] < 0.40


# ─── UCB Parameter Tuner ──────────────────────────────────────────────────────

def test_ucb_tuner_detects_best_profile():
    """UCB identifie le profil avec la meilleure WR sur 200 trials."""
    random.seed(789)
    tuner = ParameterTuner()
    best_real = "aggressive"
    for trial in range(200):
        name = tuner.select_profile(trial)
        wr = 0.65 if name == best_real else 0.45
        win = random.random() < wr
        tuner.update(name, win=win, pnl=10 if win else -5,
                      r_multiple=1.0 if win else -1.0)
    assert tuner.best_profile() == best_real


# ─── Attribution correcte ─────────────────────────────────────────────────────

def test_attribution_only_voting_strategies_credited():
    """Seules les stratégies ayant voté BUY doivent être créditées."""
    import core.adaptive as ad_mod
    ad_mod._instance = None
    agent = AdaptiveAgent()
    credited = agent.record_trade_outcome(
        regime="bull",
        strategy_votes={"trend_follower": True, "mean_reversion": False, "breakout_hunter": True},
        profile_name="balanced", win=True, pnl=10, r_multiple=1.0,
    )
    assert credited == 2


def test_attribution_non_voting_strategies_untouched():
    """Une stratégie n'ayant pas voté doit avoir son posterior inchangé."""
    import core.adaptive as ad_mod
    ad_mod._instance = None
    agent = AdaptiveAgent()
    # reversion ne vote PAS pour 50 trades
    for _ in range(50):
        agent.record_trade_outcome(
            regime="bull",
            strategy_votes={"trend_follower": True, "mean_reversion": False, "breakout_hunter": False},
            profile_name="balanced", win=True, pnl=10,
        )
    means = agent.bandit.get_posterior_means("bull")
    # trend = bcp de wins → posterior haut
    # reversion = posterior vierge (prior 0.5)
    assert means["trend_follower"] > 0.8
    assert abs(means["mean_reversion"] - 0.5) < 0.01


# ─── Thread-safety ────────────────────────────────────────────────────────────

def test_record_trade_outcome_thread_safe():
    """4 threads × 25 trades = 100 trades exact (pas de race)."""
    import core.adaptive as ad_mod
    ad_mod._instance = None
    agent = AdaptiveAgent()

    def worker():
        for _ in range(25):
            agent.record_trade_outcome(
                regime="bull",
                strategy_votes={"trend_follower": True},
                profile_name="balanced", win=True, pnl=5,
            )

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()

    total = agent.get_total_trades()
    assert total == 100, f"Race condition : {total} trades"
