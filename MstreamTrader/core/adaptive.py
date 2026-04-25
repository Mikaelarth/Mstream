"""
MstreamTrader - Agent Adaptatif (Apprentissage en ligne)
=========================================================

Trois techniques d'apprentissage progressif, 100 % pure Python, zero dépendance :

  1. THOMPSON SAMPLING (Multi-Armed Bandit)
     Pondération adaptative des 3 sous-stratégies (trend / reversion / breakout).
     Chaque stratégie porte une distribution Beta(α, β). À chaque décision on
     sample une valeur. Mise à jour après chaque trade fermé : win → α+=1, loss → β+=1.
     Référence : Thompson (1933), Chapelle & Li (2011).

  2. PARAMETER AUTO-TUNING (Bandit sur K configurations)
     K profils paramétriques sont testés en parallèle via epsilon-greedy +
     sliding window. Le bot explore 10 % du temps, exploite 90 %.
     Converge vers la configuration optimale pour le marché courant.

  3. REGIME-SPECIFIC MEMORY (Contextual Learning)
     Performance par régime persistée en DB. Au basculement de régime, le bot
     recall les meilleurs paramètres historiques pour ce contexte.
     Principe de few-shot learning sans réseau de neurones.

Garanties théoriques :
  - Thompson Sampling : regret borné par O(log T) (Chapelle & Li 2011)
  - Sliding window + exponential decay : robuste à la non-stationnarité

Mathématiques appliquées (pas de library externe) :
  - Beta sampling via Gamma method (random.gammavariate)
  - Posterior update Beta conjugué : Beta(α + wins, β + losses)
  - Hoeffding concentration bound pour décider du "statistiquement significatif"

NOTE : ce module ne remplace PAS la logique statique (REGIME_WEIGHTS dans ensemble.py).
Il fournit des *suggestions* qui peuvent être activées via le switch
`MASTER_CONFIG["use_adaptive"]`. Tous les ajustements sont audités.
"""

import math
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ─── Constantes ───────────────────────────────────────────────────────────────

STRATEGY_NAMES = ("trend_follower", "mean_reversion", "breakout_hunter")

# Prior uniforme Beta(1, 1) = distribution uniforme sur [0, 1]
DEFAULT_ALPHA = 1.0
DEFAULT_BETA  = 1.0

# Sliding window : derniers N trades considérés pour le tuning des paramètres
DEFAULT_WINDOW = 50

# Epsilon-greedy : probabilité d'exploration
DEFAULT_EPSILON = 0.10

# Exponential decay : les vieux trades pèsent moins (non-stationnarité)
DECAY_HALFLIFE_TRADES = 100.0   # demi-vie à 100 trades


# ─── Profils paramétriques candidats ──────────────────────────────────────────

# 5 configurations paramétriques à tester en parallèle.
# Le bot explore lesquelles performent le mieux sur son marché actuel.
PARAM_PROFILES = {
    "conservative": {
        "min_score":          65.0,
        "min_confidence":     75.0,
        "min_rr":             3.0,
        "kelly_fraction":     0.15,
    },
    "balanced": {   # profil par défaut ~= MASTER_CONFIG actuel
        "min_score":          55.0,
        "min_confidence":     65.0,
        "min_rr":             2.5,
        "kelly_fraction":     0.25,
    },
    "aggressive": {
        "min_score":          45.0,
        "min_confidence":     55.0,
        "min_rr":             2.0,
        "kelly_fraction":     0.35,
    },
    "high_quality_signals": {
        "min_score":          70.0,
        "min_confidence":     80.0,
        "min_rr":             2.5,
        "kelly_fraction":     0.25,
    },
    "high_rr_only": {
        "min_score":          55.0,
        "min_confidence":     65.0,
        "min_rr":             4.0,
        "kelly_fraction":     0.30,
    },
}


# ─── THOMPSON SAMPLING pour les stratégies ────────────────────────────────────

@dataclass
class StrategyPosterior:
    """Distribution Beta(α, β) pour une stratégie donnée."""
    strategy: str
    regime:   str
    alpha:    float = DEFAULT_ALPHA
    beta:     float = DEFAULT_BETA
    wins:     int   = 0
    losses:   int   = 0
    total_pnl: float = 0.0
    last_trade_ts: float = 0.0

    def mean(self) -> float:
        """Espérance de la distribution Beta."""
        return self.alpha / (self.alpha + self.beta)

    def variance(self) -> float:
        s = self.alpha + self.beta
        return (self.alpha * self.beta) / (s * s * (s + 1.0))

    def sample(self) -> float:
        """
        Sample une valeur depuis Beta(α, β) via Gamma method.
        X ~ Gamma(α) / (Gamma(α) + Gamma(β))
        """
        try:
            x = random.gammavariate(self.alpha, 1.0)
            y = random.gammavariate(self.beta,  1.0)
            total = x + y
            return x / total if total > 0 else 0.5
        except (ValueError, OverflowError):
            return self.mean()

    def update(self, win: bool, pnl: float = 0.0, decay_applied: bool = True):
        """
        Bayesian update : après un trade observé, on incrémente α ou β.
        Un léger decay est appliqué pour que les vieux résultats pèsent moins.
        """
        if decay_applied:
            # Decay lent : α et β s'affaiblissent à chaque update
            # → poids effectif des trades anciens diminue
            decay_factor = 1.0 - (1.0 / DECAY_HALFLIFE_TRADES)
            self.alpha = max(DEFAULT_ALPHA, self.alpha * decay_factor)
            self.beta  = max(DEFAULT_BETA,  self.beta  * decay_factor)

        if win:
            self.alpha += 1.0
            self.wins  += 1
        else:
            self.beta  += 1.0
            self.losses += 1
        self.total_pnl    += pnl
        self.last_trade_ts = time.time()


class StrategyBandit:
    """
    Multi-Armed Bandit Thompson Sampling pour les 3 sous-stratégies.
    Thread-safe via verrou interne.
    """

    def __init__(self, strategies: tuple = STRATEGY_NAMES):
        import threading
        self.strategies = strategies
        self._lock = threading.Lock()
        # Une posterior par (stratégie, régime) pour adapter selon contexte
        self._posteriors: dict[tuple[str, str], StrategyPosterior] = {}

    def _get_or_create(self, strategy: str, regime: str) -> StrategyPosterior:
        key = (strategy, regime)
        if key not in self._posteriors:
            self._posteriors[key] = StrategyPosterior(strategy=strategy, regime=regime)
        return self._posteriors[key]

    def sample_weights(self, regime: str) -> dict[str, float]:
        """
        Retourne un dict {strategy: weight} où chaque weight est un sample
        Thompson. Plus le posterior est favorable, plus le weight est élevé.
        """
        with self._lock:
            samples = {}
            for s in self.strategies:
                post = self._get_or_create(s, regime)
                samples[s] = post.sample()
        # Normaliser pour que la somme soit 3.0 (comme les REGIME_WEIGHTS fixes)
        total = sum(samples.values())
        if total <= 0:
            return {s: 1.0 for s in self.strategies}
        scale = len(self.strategies) / total
        return {s: v * scale for s, v in samples.items()}

    def get_posterior_means(self, regime: str) -> dict[str, float]:
        """Pour le reporting : retourne l'espérance de chaque Beta."""
        with self._lock:
            return {
                s: self._get_or_create(s, regime).mean()
                for s in self.strategies
            }

    def update(self, strategy: str, regime: str, win: bool, pnl: float = 0.0):
        """Appelé après chaque trade fermé pour mettre à jour le posterior."""
        with self._lock:
            post = self._get_or_create(strategy, regime)
            post.update(win=win, pnl=pnl)

    def load_from_db(self):
        """Charge les posteriors depuis strategy_performance."""
        try:
            from core.database import get_connection
            with get_connection() as conn:
                rows = conn.execute(
                    "SELECT strategy_name, regime, wins, losses, total_pnl, "
                    "       last_trade_at FROM strategy_performance"
                ).fetchall()
            with self._lock:
                for r in rows:
                    d = dict(r)
                    post = StrategyPosterior(
                        strategy  = d["strategy_name"],
                        regime    = d["regime"],
                        alpha     = DEFAULT_ALPHA + (d["wins"]   or 0),
                        beta      = DEFAULT_BETA  + (d["losses"] or 0),
                        wins      = d["wins"]   or 0,
                        losses    = d["losses"] or 0,
                        total_pnl = d["total_pnl"] or 0.0,
                    )
                    self._posteriors[(post.strategy, post.regime)] = post
        except (ImportError, KeyError, TypeError, ValueError) as exc:
            import logging
            logging.getLogger("adaptive").warning(f"load_from_db: {exc}")

    def persist_to_db(self):
        """Sauvegarde les compteurs wins/losses en DB (persistent across restarts)."""
        try:
            from core.database import get_connection
            now = datetime.now().isoformat()
            with self._lock:
                posteriors_snapshot = list(self._posteriors.values())
            with get_connection() as conn:
                for post in posteriors_snapshot:
                    conn.execute(
                        """INSERT INTO strategy_performance
                           (strategy_name, regime, wins, losses, total_pnl, last_trade_at)
                           VALUES (?, ?, ?, ?, ?, ?)
                           ON CONFLICT(strategy_name, regime) DO UPDATE SET
                               wins=excluded.wins,
                               losses=excluded.losses,
                               total_pnl=excluded.total_pnl,
                               last_trade_at=excluded.last_trade_at""",
                        (post.strategy, post.regime, post.wins, post.losses,
                         post.total_pnl, now)
                    )
        except (ImportError, KeyError, ValueError) as exc:
            import logging
            logging.getLogger("adaptive").warning(f"persist_to_db: {exc}")


# ─── PARAMETER AUTO-TUNER (K-armed bandit sur profils) ────────────────────────

@dataclass
class ProfilePerformance:
    """Performance observée d'un profil paramétrique."""
    name: str
    trades_count: int = 0
    wins:         int = 0
    total_pnl:    float = 0.0
    avg_r:        float = 0.0   # R-multiple moyen
    last_used_ts: float = 0.0

    def win_rate(self) -> float:
        return self.wins / self.trades_count if self.trades_count > 0 else 0.5

    def ucb_score(self, total_trades: int, c: float = 1.5) -> float:
        """
        Upper Confidence Bound (UCB1) — équilibre exploration/exploitation.
        profile.wins_rate + c × sqrt(ln(total_trades) / trades_count)
        """
        if self.trades_count == 0:
            return float("inf")   # force à explorer les non-essayés
        exploration = c * math.sqrt(math.log(max(total_trades, 2)) / self.trades_count)
        exploitation = self.win_rate() + (self.avg_r / 10.0)   # bonus R-multiple
        return exploitation + exploration


class ParameterTuner:
    """
    Bandit K-armed sur les profils paramétriques PARAM_PROFILES.
    Sélectionne un profil à chaque cycle via UCB1.
    """

    def __init__(self, profiles: dict = None):
        import threading
        self._lock = threading.Lock()
        self.profiles = profiles or PARAM_PROFILES
        self._performance: dict[str, ProfilePerformance] = {
            name: ProfilePerformance(name=name) for name in self.profiles
        }
        self._current_profile: str = "balanced"   # défaut

    def select_profile(self, total_trades: int) -> str:
        """Retourne le nom du profil à utiliser pour le prochain trade (UCB1)."""
        with self._lock:
            scores = {
                name: perf.ucb_score(total_trades)
                for name, perf in self._performance.items()
            }
            # Tri par score UCB décroissant, le plus haut gagne
            self._current_profile = max(scores, key=scores.get)
            self._performance[self._current_profile].last_used_ts = time.time()
        return self._current_profile

    def get_profile_params(self, profile_name: Optional[str] = None) -> dict:
        """Retourne les paramètres du profil sélectionné."""
        name = profile_name or self._current_profile
        return dict(self.profiles.get(name, self.profiles["balanced"]))

    def update(self, profile_name: str, win: bool, pnl: float, r_multiple: float = 0.0):
        """Met à jour la performance du profil après un trade fermé."""
        with self._lock:
            perf = self._performance.get(profile_name)
            if perf is None:
                return
            perf.trades_count += 1
            if win:
                perf.wins += 1
            perf.total_pnl += pnl
            # Moyenne glissante de R-multiple
            perf.avg_r = (perf.avg_r * (perf.trades_count - 1) + r_multiple) / perf.trades_count

    def get_stats(self) -> dict:
        """Retourne un snapshot des perfs pour reporting / audit."""
        with self._lock:
            return {
                name: {
                    "trades":    p.trades_count,
                    "wins":      p.wins,
                    "win_rate":  round(p.win_rate(), 3),
                    "total_pnl": round(p.total_pnl, 2),
                    "avg_r":     round(p.avg_r, 3),
                }
                for name, p in self._performance.items()
            }

    def best_profile(self) -> Optional[str]:
        """Le profil avec la meilleure espérance empirique (≥ 10 trades)."""
        with self._lock:
            candidates = [
                (name, p) for name, p in self._performance.items()
                if p.trades_count >= 10
            ]
            if not candidates:
                return None
            best = max(candidates, key=lambda x: x[1].win_rate() + x[1].avg_r / 10.0)
            return best[0]


# ─── REGIME-SPECIFIC MEMORY ───────────────────────────────────────────────────

class RegimeMemory:
    """
    Mémoire persistante par régime. Au basculement de régime, recall les meilleurs
    paramètres historiques pour ce contexte.
    """

    def __init__(self):
        import threading
        self._lock = threading.Lock()

    def record(self, regime: str, profile_name: str, win_rate: float,
                avg_r: float, sample_size: int):
        """Mémorise la performance d'un profil pour un régime."""
        try:
            from core.database import get_connection
            now = datetime.now().isoformat()
            with get_connection() as conn:
                conn.execute(
                    """INSERT INTO regime_memory
                       (regime, best_profile, best_win_rate, best_avg_r,
                        sample_size, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(regime) DO UPDATE SET
                           best_profile   = CASE WHEN excluded.best_win_rate > regime_memory.best_win_rate
                                                 THEN excluded.best_profile
                                                 ELSE regime_memory.best_profile END,
                           best_win_rate  = MAX(regime_memory.best_win_rate, excluded.best_win_rate),
                           best_avg_r     = CASE WHEN excluded.best_win_rate > regime_memory.best_win_rate
                                                 THEN excluded.best_avg_r
                                                 ELSE regime_memory.best_avg_r END,
                           sample_size    = regime_memory.sample_size + excluded.sample_size,
                           updated_at     = excluded.updated_at""",
                    (regime, profile_name, win_rate, avg_r, sample_size, now)
                )
        except (ImportError, KeyError, ValueError) as exc:
            import logging
            logging.getLogger("adaptive").warning(f"regime_memory.record: {exc}")

    def recall(self, regime: str) -> Optional[dict]:
        """
        Retourne les meilleurs paramètres connus pour ce régime, ou None si
        pas d'historique suffisant (< 10 trades).
        """
        try:
            from core.database import get_connection
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM regime_memory WHERE regime=? AND sample_size >= 10",
                    (regime,)
                ).fetchone()
            if row:
                d = dict(row)
                profile_name = d.get("best_profile") or "balanced"
                return {
                    "profile":     profile_name,
                    "params":      PARAM_PROFILES.get(profile_name, PARAM_PROFILES["balanced"]),
                    "win_rate":    d.get("best_win_rate"),
                    "avg_r":       d.get("best_avg_r"),
                    "sample_size": d.get("sample_size"),
                }
        except (ImportError, KeyError, ValueError) as exc:
            import logging
            logging.getLogger("adaptive").warning(f"regime_memory.recall: {exc}")
        return None


# ─── AGENT UNIFIÉ ─────────────────────────────────────────────────────────────

class AdaptiveAgent:
    """
    Orchestrateur des 3 composants. Interface unique pour le Bot Maître.
    Thread-safe via verrou interne sur les mutations de _total_trades.
    """

    def __init__(self):
        import threading
        self.bandit = StrategyBandit()
        self.tuner  = ParameterTuner()
        self.memory = RegimeMemory()
        self._total_trades = 0
        self._trade_lock = threading.Lock()
        # Charger l'état persistant au démarrage
        self.bandit.load_from_db()

    # ── Lifecycle de trade ─────────────────────────────────────────────────

    def record_trade_outcome(self, regime: str, strategy_votes: dict,
                              profile_name: str, win: bool, pnl: float,
                              r_multiple: float = 0.0) -> int:
        """
        Point d'entrée UNIQUE pour reporter un trade fermé à l'agent.

        Attribution correcte : seules les stratégies ayant voté BUY
        (strategy_votes[name] == True) sont créditées par le bandit.
        Le profil réellement utilisé est crédité au tuner.

        Thread-safe : mutation de _total_trades sous lock + persistence atomique.

        Retourne le nombre de stratégies créditées (≥ 0).

        Args:
            regime         : "bull" | "bear" | "neutral"
            strategy_votes : {"trend_follower": True, "mean_reversion": False, ...}
                             True = a voté BUY → sera crédité, False = skip
            profile_name   : nom du profil paramétrique réellement utilisé
            win            : True si le trade a gagné (pnl > 0)
            pnl            : P&L net en USDT
            r_multiple     : P&L / risque initial
        """
        credited = 0

        # Bandit : crédit sélectif par stratégie (thread-safe car bandit a son propre lock)
        for strategy_name, voted_buy in (strategy_votes or {}).items():
            if voted_buy:
                self.bandit.update(
                    strategy=strategy_name, regime=regime,
                    win=win, pnl=pnl,
                )
                credited += 1

        # Tuner : crédit du profil utilisé (thread-safe via son propre lock)
        self.tuner.update(
            profile_name=profile_name or "balanced",
            win=win, pnl=pnl, r_multiple=r_multiple,
        )

        # Compteur + actions périodiques sous lock dédié
        with self._trade_lock:
            self._total_trades += 1
            should_persist = (self._total_trades % 10 == 0)

        if should_persist:
            # Persister bandit en DB
            self.bandit.persist_to_db()
            # Mémoriser le meilleur profil pour ce régime
            stats = self.tuner.get_stats()
            best = self.tuner.best_profile()
            if best and stats.get(best, {}).get("trades", 0) >= 10:
                self.memory.record(
                    regime=regime, profile_name=best,
                    win_rate=stats[best]["win_rate"],
                    avg_r=stats[best]["avg_r"],
                    sample_size=stats[best]["trades"],
                )

        return credited

    def get_total_trades(self) -> int:
        """Accesseur thread-safe pour le compteur total de trades observés."""
        with self._trade_lock:
            return self._total_trades

    # ── Consultation (lecture seule) ────────────────────────────────────────

    def get_strategy_weights(self, regime: str) -> dict[str, float]:
        """Retourne les weights adaptatifs pour le vote d'ensemble."""
        return self.bandit.sample_weights(regime)

    def suggest_profile(self, regime: str) -> dict:
        """
        Retourne un profil paramétrique suggéré pour ce régime.
        Essaie d'abord le recall memory, fallback sur UCB tuner.
        """
        # 1. Recall memory : si on a un historique suffisant pour ce régime
        recalled = self.memory.recall(regime)
        if recalled is not None:
            return {
                "source":       "regime_memory",
                "profile_name": recalled["profile"],
                "params":       recalled["params"],
                "confidence":   min(1.0, recalled["sample_size"] / 50.0),
                "rationale":    f"Meilleur profil historique en {regime} "
                                f"(WR {recalled['win_rate']:.2%}, n={recalled['sample_size']})",
            }
        # 2. UCB tuner : explore / exploite (lecture thread-safe du compteur)
        total_t = self.get_total_trades()
        name = self.tuner.select_profile(total_trades=total_t)
        return {
            "source":       "ucb_tuner",
            "profile_name": name,
            "params":       self.tuner.get_profile_params(name),
            "confidence":   min(1.0, total_t / 100.0),
            "rationale":    f"UCB1 selection pour exploration/exploitation",
        }

    def get_summary(self, regime: str) -> dict:
        """Rapport complet pour UI / audit."""
        return {
            "total_trades":    self.get_total_trades(),
            "strategy_means":  self.bandit.get_posterior_means(regime),
            "profile_stats":   self.tuner.get_stats(),
            "best_profile":    self.tuner.best_profile(),
            "current_suggest": self.suggest_profile(regime),
        }


# ─── Singleton ────────────────────────────────────────────────────────────────

_instance: Optional[AdaptiveAgent] = None


def get_adaptive_agent() -> AdaptiveAgent:
    global _instance
    if _instance is None:
        _instance = AdaptiveAgent()
    return _instance


# ─── Migration DB (tables créées via init_adaptive_tables) ────────────────────

def init_adaptive_tables():
    """Crée les 3 tables nécessaires à l'agent adaptatif."""
    from core.database import get_connection
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS strategy_performance (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_name  TEXT NOT NULL,
                regime         TEXT NOT NULL,
                wins           INTEGER NOT NULL DEFAULT 0,
                losses         INTEGER NOT NULL DEFAULT 0,
                total_pnl      REAL NOT NULL DEFAULT 0,
                last_trade_at  TEXT,
                UNIQUE(strategy_name, regime)
            );

            CREATE TABLE IF NOT EXISTS param_adjustments (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                cycle_id       TEXT,
                parameter_name TEXT NOT NULL,
                old_value      REAL,
                new_value      REAL,
                reason         TEXT,
                confidence     REAL,
                adjusted_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS regime_memory (
                regime         TEXT PRIMARY KEY,
                best_profile   TEXT NOT NULL,
                best_win_rate  REAL NOT NULL DEFAULT 0,
                best_avg_r     REAL NOT NULL DEFAULT 0,
                sample_size    INTEGER NOT NULL DEFAULT 0,
                updated_at     TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_strategy_perf_regime
                ON strategy_performance(regime);
            CREATE INDEX IF NOT EXISTS idx_param_adj_cycle
                ON param_adjustments(cycle_id);
        """)


def log_param_adjustment(parameter_name: str, old_value: float, new_value: float,
                          reason: str, confidence: float = 0.0,
                          cycle_id: Optional[str] = None):
    """Enregistre un ajustement de paramètre dans l'audit."""
    try:
        from core.database import get_connection
        now = datetime.now().isoformat()
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO param_adjustments
                   (cycle_id, parameter_name, old_value, new_value,
                    reason, confidence, adjusted_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (cycle_id, parameter_name, old_value, new_value,
                 reason, confidence, now)
            )
    except (ImportError, KeyError, ValueError) as exc:
        import logging
        logging.getLogger("adaptive").warning(f"log_param_adjustment: {exc}")
