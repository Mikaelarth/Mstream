# MstreamTrader — Niveau Institutional Grade

Ce document décrit les 10 techniques avancées qui font passer MstreamTrader
d'un bot retail à un moteur de trading de niveau hedge fund / prop trading firm.

> **Statut : TOUTES INTÉGRÉES AU BOT LIVE.** Plus aucun module dormant. Chaque technique
> est activement utilisée à chaque cycle du Bot Maître. Voir [PROJECT_STATE.md](PROJECT_STATE.md)
> pour le statut détaillé de chaque fonctionnalité.

---

## Architecture complète

Le Bot Maître orchestre désormais **10 modules spécialisés** qui coopèrent :

```
                          ┌─────────────────────────┐
                          │    CIRCUIT BREAKER      │
                          │  (kill switch pro)      │
                          └────────────┬────────────┘
                                       │ autorise/bloque
                                       ▼
       ┌─────────────┐        ┌─────────────────┐        ┌─────────────┐
       │  HEALTH     │───────►│    BOT MAITRE   │◄───────│  CHECKPOINT │
       │   CHECKS    │        │   (cycle 1h)    │        │  (recovery) │
       └─────────────┘        └────────┬────────┘        └─────────────┘
                                       │
         ┌─────────────────────────────┼─────────────────────────────┐
         ▼                             ▼                             ▼
  ┌──────────────┐            ┌────────────────┐            ┌────────────────┐
  │    REGIME    │            │   CORRELATION  │            │    ENSEMBLE    │
  │  BULL/BEAR   │            │     MATRIX     │            │   (3 stratés)  │
  │  + Transition│            │   (vraie div.) │            │                │
  └──────────────┘            └────────────────┘            └────────────────┘
         │                             │                             │
         └──────────┬──────────────────┴──────────────┬──────────────┘
                    ▼                                 ▼
            ┌──────────────────┐              ┌───────────────────┐
            │ POSITION SIZING  │              │   AUDIT TRAIL     │
            │ Kelly + Vol-Tgt  │              │  (tout trace)     │
            └──────────────────┘              └───────────────────┘
```

---

## 1. Circuit Breaker Multi-Niveaux

[core/circuit_breaker.py](../MstreamTrader/core/circuit_breaker.py)

**Inspiré** des coupe-circuits des trading floors institutionnels (NYSE Rule 80B).

### 4 niveaux d'état

| État | Ce qui se passe | Trigger |
|---|---|---|
| 🟢 HEALTHY | Fonctionnement normal | — |
| 🟡 WARNING | Audit renforcé, trading continue | Anomalies mineures |
| 🔴 TRIGGERED | Entrées bloquées, surveillance SL/TP OK | 5 SL consécutifs, −10% en 4h, DD 20% |
| ⛔ FROZEN | Arrêt TOTAL (même exits) | 5 erreurs API consécutives |

### Auto-recovery
- WARNING → HEALTHY après 2h sans incident
- TRIGGERED → WARNING après 12h (surveillance dégressive)
- FROZEN → **intervention manuelle requise**

### Détections actives
- Pertes SL consécutives (seuil configurable)
- Drawdown rapide (% en fenêtre de temps)
- Drawdown total (peak-to-trough)
- Perte anormale (> 3× avg_loss)
- Échecs API répétés

---

## 2. Kelly Criterion Fractional + Volatility Targeting

[core/position_sizing.py](../MstreamTrader/core/position_sizing.py)

**La formule** qui maximise la croissance long-terme d'un capital soumis à des paris favorables :

```
f* = (p × b − q) / b
  p : probabilité de gain (win rate)
  q : probabilité de perte
  b : gain moyen / perte moyenne
```

### Pourquoi FRACTIONAL Kelly (25%)

Kelly complet est théoriquement optimal mais **très agressif** (50% drawdown fréquents). Les hedge funds utilisent systématiquement **1/4 Kelly** :
- Quarter Kelly = 25% du Full Kelly
- Réduit la variance de 75% pour une perte de ~20% du growth
- Compense l'incertitude sur les estimations de win_rate/avg_win

### Volatility Targeting

Position size ajustée à la volatilité réalisée :
- Marché calme (ATR 1 % prix) → **positions × 2** (target = 2 %)
- Marché volatile (ATR 4 %) → **positions / 2**

### Sizing combiné

Le bot prend le MINIMUM de 3 contraintes :
1. Kelly fractional
2. Vol-adjusted size (pour volatilité cible)
3. Max risk absolu (hard cap 2 % par trade)

---

## 3. Dynamic Correlation Matrix

[core/correlation.py](../MstreamTrader/core/correlation.py)

**Le piège #1 de la diversification crypto** : BTC + ETH + BNB + SOL sont corrélés à 85-95 %. Le bot ancien pouvait ouvrir 4 positions corrélées = 1 seul pari déguisé.

### Technique
- Pearson correlation sur les **retours** (pas les prix)
- Rolling 30 jours
- Mise à jour à chaque cycle
- **Blocage** : refus d'ouvrir si corrélation > 0.75 avec position déjà ouverte

### Diversification score
Pour mesurer la "vraie diversification" du portefeuille :
```
score = 1 − moyenne(|corrélations|)
1.0 = parfait / 0.0 = tout identique
```

---

## 4. Ensemble Voting System (3 sous-stratégies)

[core/ensemble.py](../MstreamTrader/core/ensemble.py)

**Au lieu d'UNE stratégie, TROIS votent** :

| Stratégie | Philosophie | Indicateurs clés |
|---|---|---|
| **Trend Follower** | "The trend is your friend" | EMA 12/26/50, MACD |
| **Mean Reversion** | "Extremes revert" | RSI extrême, BB bands |
| **Breakout Hunter** | "Buy breakouts" | Support/Résistance, BB squeeze |

### Vote pondéré par régime

| Stratégie | Bull | Neutral | Bear |
|---|---:|---:|---:|
| Trend Follower | 1.3× | 0.8× | 0.4× |
| Mean Reversion | 0.6× | 1.2× | 0.5× |
| Breakout Hunter | 1.0× | 1.0× | 0.6× |

En bear market, trend following est pénalisé (piégeux), mean reversion aussi (falling knives). Le bot devient quasi-inactif.

### Règle de qualification
Signal validé si **≥ 2 stratégies d'accord** + score ensemble > 30 + confiance > 50 %.

---

## 5. Multi-Timeframe Confluence

[core/mtf.py](../MstreamTrader/core/mtf.py)

**Standard pro** : ne jamais trader sur un seul timeframe. Exiger la confluence :
- Daily → tendance de fond
- 4h → momentum
- 1h → timing d'entrée

Le bot calcule un score de confluence 0-3. Entrée seulement si **≥ 2/3 timeframes alignés** dans la même direction.

### Protection contre les pièges
Si le TF long-terme est clairement bearish (strength > 30), l'entrée BUY est refusée même si les TF courts sont bullish. Évite d'acheter un "bounce" dans un bear market.

---

## 6. Détection de Transition de Régime

[core/regime.py](../MstreamTrader/core/regime.py#L125) — `detect_regime_transition()`

**Signal AVANCÉ** : détecter les bascules **avant** qu'elles ne soient officielles.

### Signaux détectés
1. **Golden Cross / Death Cross** (EMA 50 vs EMA 200)
2. **Prix franchit EMA 200 avec momentum** (>5% en 10 jours)
3. **Slope EMA 200 s'inverse** (le trend long-terme change)
4. **Prix proche de la frontière** ±2 %

### Output
```python
{
    "transitioning":     True,
    "from_regime":       "bear",
    "to_regime":         "neutral",
    "transition_score":  0.73,
    "signals":           ["Golden Cross il y a 4j", "Momentum haussier +7.2%"],
    "days_to_bascule":   3,
}
```

Permet au bot de commencer à adoucir ses critères **avant** la bascule officielle.

---

## 7. Walk-Forward Analysis

[core/walk_forward.py](../MstreamTrader/core/walk_forward.py)

**Validation hors-sample** utilisée dans les hedge funds et publications académiques.

### Principe
Un backtest simple peut être **overfit** (paramètres qui marchent par chance sur cette période). Walk-forward découpe l'historique en fenêtres glissantes et ne mesure que la performance **hors du training set**.

### Exemple

Avec 120 jours, window=60, step=30 :
```
Fenêtre 1 : j0-j60    → train 0-42, test 42-60 (OOS)
Fenêtre 2 : j30-j90   → train 30-72, test 72-90 (OOS)
Fenêtre 3 : j60-j120  → train 60-102, test 102-120 (OOS)
```

On ne backteste que les parties test. Agrégation = moyenne des OOS.

### Critère de robustesse

Une stratégie est considérée **robuste** si :
- consistency > 60 % (au moins 60 % des fenêtres en gain)
- avg Sharpe > 0.5
- avg Profit Factor > 1.2

---

## 8. Audit Trail Structuré

[core/audit.py](../MstreamTrader/core/audit.py)

**Traçabilité institutional** : chaque décision du bot est horodatée, typée et persistée en DB avec le raisonnement complet.

### Table `audit_log`

15 types d'événements :
- `SIGNAL_ANALYZED` — signal calculé
- `SIGNAL_QUALIFIED` — passe les filtres
- `SIGNAL_REJECTED` — rejeté (avec raison)
- `ENTRY_EXECUTED` — achat
- `POSITION_CLOSED` — vente + P&L
- `REGIME_CHANGED` — bascule de régime
- `CIRCUIT_BREAKER` — événement du kill switch
- `CORRELATION_BLOCK` — refus par corrélation
- `KELLY_SIZING` — calcul de taille
- `CYCLE_COMPLETED` — résumé de cycle
- etc.

### Requêtes possibles
```python
from core.audit import query_events, cycle_summary

# Tous les signaux rejetés hier
query_events(event_type="SIGNAL_REJECTED", since="2026-04-23")

# Reconstitution complète d'un cycle
cycle_summary("cycle-1714060800-abc123")
```

---

## 9. Health Checks Continu

[core/health.py](../MstreamTrader/core/health.py)

Checks périodiques :
- Ping Binance + latence
- Ping CoinGecko + latence
- Fraîcheur des données (stale detection)
- Sanity des prix (low > high, prix nul, gap > 15 % en 1 bougie)
- Divergence inter-sources (Binance vs CoinGecko > 3 %)

Tout échec → escalade au Circuit Breaker.

---

## 10. Checkpointing & Recovery

[core/checkpoint.py](../MstreamTrader/core/checkpoint.py)

Snapshot périodique de l'état volatile du bot (circuit breaker, régime, peak capital, etc.) en DB.

**Au redémarrage** (crash, kill, reboot) : le bot recharge automatiquement le dernier snapshot de moins de 24h et reprend là où il était.

Les positions ouvertes sont déjà persistées via `open_positions` → aucune perte possible.

---

## Intégration complète dans le cycle

Chaque cycle du Bot Maître exécute :

```python
1. Génère un cycle_id unique (pour l'audit)
2. Rafraîchit le régime si TTL expiré (→ log audit si change)
3. Auto-recover le Circuit Breaker (timeout-based)
4. Report du capital total au Circuit Breaker
5. Si Circuit FROZEN : STOP (pas même les exits)
6. Gère trailing SL + exits
7. Si Circuit autorise : look_for_entries_advanced :
   - Filtre de base (seuils régime)
   - Ensemble vote (3 stratégies votent)
   - Correlation block (refuse si corrélé)
   - Kelly sizing (taille optimale)
   - Exécution + audit complet
8. Log cycle completed (stats résumées)
```

---

## Metrics de performance

Disponibles via [core/metrics.py](../MstreamTrader/core/metrics.py) :

| Métrique | Cible pro | Cible retail |
|---|---:|---:|
| Sharpe annualisé | > 2.0 | > 1.0 |
| Sortino | > 2.5 | > 1.5 |
| Calmar | > 3.0 | > 1.0 |
| Max Drawdown | < 10 % | < 20 % |
| Profit Factor | > 2.0 | > 1.5 |
| Win Rate | 45-55 % | 40 %+ |
| R-multiple moyen | > 0.5 | > 0.3 |

---

## Utilisation

Tout est activé automatiquement dans le Bot Maître. Pour désactiver une feature (test A/B) :

```python
# Dans core/auto_trader.py MASTER_CONFIG
"use_ensemble":          False,   # désactive le vote
"use_correlation_block": False,   # désactive le filtre corrélation
"use_kelly_sizing":      False,   # fallback sizing fixe
"use_mtf_confluence":    False,   # désactive multi-timeframe
"use_regime_transition": False,   # pas de blending transition

# Paramètres des tâches périodiques
"checkpoint_every_n_cycles":   6,    # 1×/6h
"health_check_every_n_cycles": 1,    # chaque cycle
"audit_purge_every_n_cycles":  24,   # 1×/jour
"audit_keep_days":             30,
```

Pour configurer le Circuit Breaker :
```python
from core.circuit_breaker import get_circuit_breaker, CircuitConfig

cb = get_circuit_breaker()
cb.config.max_consecutive_sl = 3        # plus strict
cb.config.rapid_drawdown_pct = 8.0      # déclenchement plus rapide
```

---

## Ordre de mérite des features

Si tu dois prioriser, voici l'impact approximatif :

1. 🥇 **Kelly Criterion** — change la rentabilité long-terme du simple au double
2. 🥈 **Circuit Breaker** — évite la catastrophe en bear surprise
3. 🥉 **Correlation Matrix** — vraie diversification = max DD réduit
4. **Ensemble Voting** — réduit les faux signaux
5. **Régime Filter** — filtre les pièges en bear
6. **Walk-Forward** — valide la robustesse (avant live)
7. **Audit Trail** — debug + amélioration continue
8. **MTF Confluence** — qualité des entrées
9. **Health Checks** — fiabilité opérationnelle
10. **Checkpointing** — résilience aux pannes
