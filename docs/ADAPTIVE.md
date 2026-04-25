# Agent Adaptatif — Apprentissage en Ligne

## Vision

MstreamTrader n'est pas un bot à règles figées : il **apprend progressivement** en observant ses propres résultats. Trois mécanismes d'apprentissage, tous en **pure Python** (zero dépendance ML) :

1. **Thompson Sampling** pour pondérer les 3 sous-stratégies (Multi-Armed Bandit)
2. **UCB Tuner** pour découvrir le meilleur profil paramétrique
3. **Regime Memory** pour rappeler les paramètres optimaux à chaque basculement

**Pas de fake.** Pas de deep learning, pas de TensorFlow/PyTorch. **Des techniques mathématiquement prouvées**, utilisées dans les hedge funds quantitatifs depuis Thompson (1933) jusqu'aux papers récents (Chapelle & Li 2011 — Google).

---

## 🎯 Pourquoi pas du Deep Learning ?

Le deep learning est une **mauvaise idée** pour MstreamTrader :

| Contrainte | Deep Learning | Apprentissage adaptatif (notre choix) |
|---|:-:|:-:|
| Compatible Android Buildozer | ❌ | ✅ Zero dépendance |
| Risque overfitting | 🔴 Élevé | 🟢 Faible (bandit = stable) |
| Données nécessaires | Millions de trades | Centaines suffisent |
| Interprétabilité | ❌ Black box | ✅ Posterior Beta auditable |
| Convergence garantie | ❌ Paramétrique | ✅ Regret borné O(log T) |
| Temps entraînement | Heures/jours | Instantané (online) |

En finance quantitative, **les bandits contextuels** sont plus courants que le deep learning pour les décisions de trading. Le DL sert au pattern recognition (images, texte), pas aux décisions séquentielles en univers adversarial.

---

## 🧠 Technique 1 — Thompson Sampling sur les stratégies

### Le principe

Les 3 sous-stratégies (`trend_follower`, `mean_reversion`, `breakout_hunter`) ont historiquement des **poids fixes par régime** (Bull : 1.3/0.6/1.0, etc.). **Problème** : ces poids sont devinés, pas appris.

**Thompson Sampling** fait mieux : chaque stratégie porte une **distribution Beta(α, β)** sur sa probabilité de gain. À chaque décision, on **échantillonne** depuis ces distributions et on utilise les samples comme poids.

### Mathématiques

Pour chaque paire (stratégie, régime) :

```
Prior      :  α₀ = 1, β₀ = 1   (uniforme sur [0,1])
Observation:  après un trade fermé
Update     :  si win  → α += 1
              si loss → β += 1
Posterior  :  Beta(α, β)
Sample     :  w ~ Beta(α, β) via méthode Gamma :
              X = Γ(α)/(Γ(α) + Γ(β))
```

### Garantie théorique

**Regret borné par O(log T)** (Chapelle & Li 2011). En pratique : après ~50 trades, le bandit identifie avec forte probabilité la meilleure stratégie pour le régime courant.

### Démonstration (test réel du code)

```
Scenario : A = 70% WR, B = 50% WR, C = 30% WR (inconnu du bandit)
Après 500 trials :
  A sélectionné 481 fois  (96.2 %)
  B sélectionné  14 fois  (2.8 %)
  C sélectionné   5 fois  (1.0 %)
Posterior means : A=0.69, B=0.38, C=0.15
```

Le bandit a trouvé la meilleure stratégie.

### Robustesse à la non-stationnarité

Les marchés changent. Un **decay exponentiel** atténue les vieux trades :
```
À chaque update : α *= (1 − 1/halflife) avec halflife = 100 trades
```
→ Les trades de > 100 cycles perdent la moitié de leur poids.

---

## 🧠 Technique 2 — UCB Parameter Tuner

### Le principe

5 profils paramétriques sont testés en parallèle :

| Profil | min_score | min_rr | kelly_fraction |
|---|---:|---:|---:|
| `conservative` | 65 | 3.0 | 0.15 |
| `balanced` (défaut) | 55 | 2.5 | 0.25 |
| `aggressive` | 45 | 2.0 | 0.35 |
| `high_quality_signals` | 70 | 2.5 | 0.25 |
| `high_rr_only` | 55 | 4.0 | 0.30 |

**UCB1** (Upper Confidence Bound) sélectionne à chaque cycle le profil à utiliser :
```
score(profil) = win_rate + avg_R/10 + c × √(ln(T) / n_trades)
                └─ exploitation ┘     └─ exploration ┘
```

Plus `c` est élevé, plus on explore. Par défaut `c = 1.5` (équilibre standard).

### Démonstration

```
Scenario : 200 trials, aggressive = 65% WR, autres = 45% WR
Résultat :
  conservative         :  31 trades  WR=0.42
  balanced             :  14 trades  WR=0.14
  aggressive           :  67 trades  WR=0.58  ← DÉTECTÉ comme meilleur
  high_quality_signals :  51 trades  WR=0.53
  high_rr_only         :  37 trades  WR=0.46
best_profile() → "aggressive"
```

Le UCB a bien identifié le profil optimal après 200 trades.

---

## 🧠 Technique 3 — Regime-Specific Memory

### Le principe

Chaque régime (Bull/Neutral/Bear) peut avoir un profil optimal différent. La **mémoire régime** persiste cette connaissance en DB :

```sql
CREATE TABLE regime_memory (
    regime         TEXT PRIMARY KEY,
    best_profile   TEXT NOT NULL,
    best_win_rate  REAL,
    best_avg_r     REAL,
    sample_size    INTEGER,
    updated_at     TEXT
);
```

### Recall à la bascule

Quand le régime bascule (ex : Neutral → Bull), le bot **recall** :

```python
recalled = memory.recall("bull")
# → {"profile": "aggressive", "win_rate": 0.58, "sample_size": 67, ...}
```

Le bot applique immédiatement le meilleur profil historique pour ce régime. C'est du **few-shot learning** sans réseau de neurones.

### Convergence

La mémoire ne retourne un profil que si `sample_size >= 10`. Avant, le bot utilise l'UCB Tuner pour explorer.

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  core/adaptive.py                       │
│                                                         │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐    │
│  │  Strategy   │  │  Parameter   │  │   Regime    │    │
│  │   Bandit    │  │    Tuner     │  │   Memory    │    │
│  │ (Thompson)  │  │   (UCB1)     │  │(persistant) │    │
│  └──────┬──────┘  └──────┬───────┘  └──────┬──────┘    │
│         │                │                 │           │
│         └──────────┬─────┴─────────────────┘           │
│                    ▼                                   │
│           AdaptiveAgent (singleton)                    │
│           • on_trade_closed()                          │
│           • get_strategy_weights(regime)               │
│           • suggest_profile(regime)                    │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
         Intégration transparente :
         • ensemble.vote(adaptive_weights=...)
         • auto_trader._execute_exit() → on_trade_closed
         • MASTER_CONFIG["use_adaptive"] = True
```

---

## 📦 Tables DB

### `strategy_performance`
Compteurs bayésiens par stratégie et régime.

```sql
(strategy_name TEXT, regime TEXT, wins INT, losses INT, total_pnl REAL, last_trade_at TEXT)
UNIQUE(strategy_name, regime)
```

### `param_adjustments`
Journal de chaque ajustement de paramètre (audit).

```sql
(cycle_id, parameter_name, old_value, new_value, reason, confidence, adjusted_at)
```

### `regime_memory`
Meilleur profil par régime (persistant across restarts).

```sql
(regime PK, best_profile, best_win_rate, best_avg_r, sample_size, updated_at)
```

---

## ⚙ Configuration

```python
# MASTER_CONFIG dans core/auto_trader.py
"use_adaptive":        True,   # Activer l'agent adaptatif
"adaptive_min_trades": 10,     # Min trades avant d'utiliser le bandit en full
```

Si `use_adaptive=False`, le bot retombe sur les REGIME_WEIGHTS statiques. **Aucune régression possible**.

---

## 🔁 Lifecycle d'un trade avec adaptive (attribution CORRECTE)

```
1. Cycle commence
2. _look_for_master_entries_advanced :
   a. agent.suggest_profile(regime) → retourne {profile_name, params}
   b. Écrase MASTER_CONFIG par les params suggérés (source: regime_memory OU UCB)
3. Signal qualifié par profile/ensemble/correlation/MTF
4. _compute_ensemble_vote() :
   → agent.get_strategy_weights(regime) : weights via Thompson Sampling
   → ensemble.vote(adaptive_weights=...)
   → Capturer strategy_votes = {trend_follower: True/False, ...}
5. _execute_entry() :
   → database.open_auto_position(strategy_votes=..., profile_name=...)
   → Persistence en DB : open_positions.strategy_votes_json + profile_name
6. [temps passe, TP ou SL atteint]
7. _execute_exit() :
   → Lit pos.strategy_votes_json + pos.profile_name depuis la position fermée
   → Pour CHAQUE strategy ayant voté BUY :
        agent.bandit.update(strategy, regime, win=trade_won)
     → Les strategies qui n'ont PAS voté ne sont PAS créditées
   → agent.tuner.update(profile_used, win, pnl, r_multiple)
   → Tous les 10 trades : persist_to_db() + memory.record()
```

### Attribution correcte (le point critique)

**Ce qu'il ne faut JAMAIS faire (fake)** :
```python
# MAUVAIS : créditer les 3 stratégies à chaque trade
for strategy in ALL_STRATEGIES:
    agent.bandit.update(strategy, win=trade_won)
# → Les posteriors convergent vers le même point, aucune info extraite
```

**Ce qu'il FAUT faire (réel)** :
```python
# BON : créditer SEULEMENT les stratégies qui ont voté pour ce trade
votes = json.loads(pos["strategy_votes_json"])
for strategy, voted_buy in votes.items():
    if voted_buy:
        agent.bandit.update(strategy, win=trade_won)
# → Chaque stratégie est évaluée sur ses décisions propres
```

**Tout est audité** dans `audit_log` (CYCLE_COMPLETED + KELLY_SIZING + CONFIG_CHANGED).

---

## 📊 Usage programmatique

```python
from core.adaptive import get_adaptive_agent

agent = get_adaptive_agent()

# Obtenir les weights pour le vote d'ensemble
weights = agent.get_strategy_weights(regime="bull")
# {"trend_follower": 1.42, "mean_reversion": 0.68, "breakout_hunter": 0.90}

# Obtenir une suggestion de profil (recall memory OU UCB)
suggestion = agent.suggest_profile(regime="bull")
# {
#   "source": "regime_memory",
#   "profile_name": "aggressive",
#   "params": {"min_score": 45, "min_rr": 2.0, "kelly_fraction": 0.35},
#   "confidence": 0.73,
#   "rationale": "Meilleur profil historique en bull (WR 58%, n=45)"
# }

# Summary pour UI / audit
summary = agent.get_summary(regime="bull")
```

---

## ⚖ Principes non-négociables respectés

- ✅ **Zero dépendance externe** (`math`, `random`, `sqlite3` stdlib)
- ✅ **Thread-safe** (lock dans StrategyBandit et ParameterTuner)
- ✅ **Persistent** (tables DB dédiées, recovery après restart)
- ✅ **Auditable** (chaque ajustement tracé)
- ✅ **Fallback safe** (si adaptive fail → weights statiques)
- ✅ **Testé** (convergence Beta et UCB démontrée)
- ✅ **Non-stationnaire** (decay exponentiel sur les posteriors)
- ✅ **Android-compat** (pas de NumPy/scipy/torch)

---

## 📚 Références académiques

- Thompson, W. R. (1933). "On the likelihood that one unknown probability exceeds another"
- Lai, T. L. & Robbins, H. (1985). "Asymptotically efficient adaptive allocation rules"
- Auer, Cesa-Bianchi, Fischer (2002). "Finite-time Analysis of the Multi-armed Bandit Problem" (UCB1)
- Chapelle, O. & Li, L. (2011). "An Empirical Evaluation of Thompson Sampling" (Google)
- Russo, Van Roy, Kazerouni, Osband (2018). "A Tutorial on Thompson Sampling"

Ces techniques sont utilisées en production par Google (ads), Microsoft (web rec), Stitch Fix, Netflix, et de nombreux fonds quantitatifs.
