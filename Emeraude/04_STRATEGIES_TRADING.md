# 04 — Stratégies de Trading

> Le bot ne suit **pas une stratégie unique**. Il a **plusieurs
> stratégies indépendantes** qui votent, et le **vote pondéré
> évolue** selon ce que chaque stratégie a démontré (cf. doc 03).

---

## Pourquoi multi-stratégies ?

| Stratégie unique | Multi-stratégies |
|---|---|
| Sur-performe dans un seul régime de marché | Au moins une marche dans chaque régime |
| Drawdown profond quand son régime change | Diversification temporelle des pertes |
| Pas d'apprentissage possible | Comparer entre elles → meilleure stratégie émerge |
| Sensible au sur-optimisation des paramètres | Compense les biais individuels |

Coût : un peu plus de complexité de code, mais déjà absorbée par
`core/ensemble.py`.

---

## Les 3 stratégies actuelles (déjà codées)

Module : `core/ensemble.py`

### 1. **Trend Follower**

**Hypothèse** : *"The trend is your friend"* — un coin qui monte
continue de monter.

**Indicateurs** :
- EMA 12 vs EMA 26 (golden cross)
- Prix vs EMA 50 (filtre tendance long terme)
- MACD line vs signal line
- Histogramme MACD croissant

**Score max** : ±90 (très opportuniste)

**Quand elle marche** : marchés haussiers étendus (Bull market).

**Quand elle perd** : ranges plats (faux signaux), réversions
rapides.

### 2. **Mean Reversion**

**Hypothèse** : *"Les extrêmes reviennent à la moyenne"* — un coin
extrêmement survendu va rebondir.

**Indicateurs** :
- RSI < 25 ou > 75 (extrêmes)
- Position dans bandes de Bollinger (extrême basse / haute)
- Stochastique < 15 ou > 85 (double sur/sous-vente)

**Score max** : ±90

**Quand elle marche** : marchés en range (sideways).

**Quand elle perd** : tendances fortes (achats prématurés en bear,
ventes prématurées en bull).

### 3. **Breakout Hunter**

**Hypothèse** : *"Buy high, sell higher"* — quand un coin casse une
résistance avec volume, il continue.

**Indicateurs** :
- Cassure de résistance récente (< 3 % au-dessus)
- Cassure de support récente (pour SELL)
- Bandes de Bollinger en squeeze (volatilité comprimée)
- ATR confirmation (momentum)

**Score max** : ±60

**Quand elle marche** : transitions de régime, breakouts confirmés.

**Quand elle perd** : faux breakouts, marchés très calmes.

---

## Vote pondéré (déjà codé)

Module : `core/ensemble.py:vote()`

```python
final_score = Σ (vote_strategy × confidence_strategy × weight_strategy)
              / Σ weights

agreement = nombre de stratégies d'accord avec final_vote
```

Validation `is_ensemble_qualified` :
- Vote final = BUY ou STRONG_BUY
- Au moins 2/3 stratégies d'accord
- Score >= 30
- Confidence >= 50

---

## Pondération adaptative (cf. doc 03)

Les poids ne sont **pas fixes**. Ils varient selon :

### 1. Régime de marché courant (`REGIME_WEIGHTS`)

| Régime | Trend | Mean Rev | Breakout |
|---|:-:|:-:|:-:|
| Bull | 1.3 | 0.6 | 1.0 |
| Neutral | 0.8 | 1.2 | 1.0 |
| Bear | 0.4 | 0.5 | 0.6 |

### 2. Performance récente (Thompson Sampling)

L'agent adaptatif (`core/adaptive.py:AdaptiveAgent`) maintient une
distribution Beta sur le succès de chaque stratégie. À chaque cycle :

```python
adaptive_weights = adaptive_agent.get_strategy_weights()
# Plus la stratégie a gagné, plus son poids est haut
ensemble.vote(coin_id, indicators_, regime, adaptive_weights=...)
```

Les `adaptive_weights` **écrasent** les `REGIME_WEIGHTS` quand
l'apprentissage a assez de données (> 30 trades).

---

## Filtres de qualité (avant exécution réelle)

Une fois le vote ensemble qualifié, le pipeline applique :

### 1. Filtre régime BTC (optionnel, défaut OFF en backtest UI)

`use_regime_filter=True` → bot skip les BUY si BTC en bear daily.

### 2. Filtre tendance EMA50 (optionnel, défaut OFF)

`require_uptrend_for_buy=True` → bot skip BUY si price < EMA50.

### 3. Filtre corrélation

`use_correlation_block=True` → refuse d'ouvrir un trade sur un coin
corrélé > 0.75 avec une position déjà ouverte.

### 4. Filtre Multi-Timeframe Confluence

`use_mtf_confluence=True` → exige confluence 1h+4h+1d (déjà codé,
désactivé en backtest UI car nécessite multi-tf data simultanées).

### 5. Position Sizing Kelly Fractional

`core/position_sizing.optimal_position_size()` calcule la taille
optimale selon Kelly + cap volatility targeting + cap absolu (% du
budget).

---

## Configuration champion validée empiriquement (avril 2026)

Walk-forward 365j 4h sur BTC/ETH/SOL/BNB :

| Paramètre | Valeur | Justification |
|---|:-:|---|
| `min_score` | 45 | Filtre les signaux faibles (noise) |
| `min_confidence` | 30 | Permettre signaux modérés mais qualifiés |
| `min_rr` | 1.5 (forcé à 2.0 dans `_compute_stop_take`) | Espérance positive |
| `max_positions` | 1 | Avec 20 USD, focus sur le meilleur signal |
| `correlation_block` | True | Évite cascades SL sur coins corrélés |
| `require_uptrend_for_buy` | True | Pas de catching falling knives |
| `cooldown_candles` | 6 | 24h sur 4h candles |
| `use_ensemble` (backtest) | False | Trop strict sur historique court |
| `use_ensemble` (LIVE) | True | Avantage en production avec apprentissage |
| `use_regime_filter` | False | BTC daily nécessite 200j data, pas tjs dispo |
| `use_mtf_confluence` (backtest) | False | Mono-timeframe par run |
| `use_mtf_confluence` (LIVE) | True | OK avec data live multi-tf |

**Résultats walk-forward** : Sharpe avg +0.93, PF avg 3.03, Win rate
40 %, 8 trades / fenêtre 30j.

**État** : édge marginal (PF > 1 = profitable, Sharpe < 1 = pas
encore robuste). Suffisant pour démarrage 20 USD, à améliorer.

---

## Configuration appliquée en LIVE (sur smartphone)

Différence importante : le bot **LIVE** active **plus de filtres**
que le backtest UI car :
- Il a accès aux données multi-timeframe (1h + 4h + 1d simultanées)
- L'agent adaptatif accumule de la mémoire dans le temps
- Le risque est plus important (argent réel)

Configuration LIVE recommandée :
```python
MASTER_CONFIG = {
    "min_score":            55,        # Plus strict en réel
    "min_confidence":       65.0,
    "min_rr":               2.5,
    "risk_pct":             5.0,       # 5% par trade = 1 USD sur 20 USD
    "max_positions":        1,         # Cohérent avec petit capital
    "max_capital_pct":      80.0,
    "use_ensemble":         True,      # Activé en LIVE
    "use_correlation_block": True,
    "use_mtf_confluence":   True,      # Activé en LIVE
    "use_regime_filter":    True,      # Si BTC daily disponible
    ...
}
```

---

## Évolution future (pistes documentées)

### Pistes pour améliorer l'edge (chantier ouvert)

1. **Volume confirmation** : exiger volume > 1.5× moyenne 20j pour
   valider un signal. Déjà partiellement présent (volume_trend) mais
   pas dans le score final.

2. **Pullback detection** : ne BUY qu'après une correction ≥ 2 ATR
   dans une tendance haussière. Évite les FOMO entries.

3. **Mean reversion plus stricte** : RSI < 20 (vs 25 actuel) +
   confluence Bollinger lower band touchée. Réduire les faux signaux.

4. **Stop-loss dynamique** : trailing serré après +1R atteint
   (verrouille le profit). Déjà partiel.

5. **Tester sur historique long** (2-3 ans) : permet de valider
   robustesse cross-régime. Bloqué par limite 1000 candles Binance
   public klines → besoin source données alternative.

6. **Hedging** : actuellement long-only. Possibilité de short via
   Binance Futures (mais hors scope pour 20 USD).

---

## Diagramme du pipeline complet

```
                         CYCLE 60 MIN
                              │
                              ▼
                    ┌──────────────────────┐
                    │  Fetch market data   │
                    └──────────┬───────────┘
                               │
                               ▼
              ┌──────────────────────────────────┐
              │  Détecter régime BTC EMA200       │
              │  Bull / Bear / Neutral            │
              └────────────────┬─────────────────┘
                               │
                               ▼
              ┌──────────────────────────────────┐
              │   Pour chaque coin (8 majeurs)    │
              │   Compute indicators              │
              └────────────────┬─────────────────┘
                               │
                               ▼
              ┌──────────────────────────────────┐
              │   3 stratégies votent             │
              │   Trend / MeanRev / Breakout      │
              └────────────────┬─────────────────┘
                               │
                               ▼
              ┌──────────────────────────────────┐
              │   Pondération adaptative          │
              │   Régime × Thompson Sampling      │
              └────────────────┬─────────────────┘
                               │
                               ▼
              ┌──────────────────────────────────┐
              │   Filtres :                       │
              │   - Profile régime (score, RR)    │
              │   - Corrélation                   │
              │   - MTF confluence                │
              │   - Uptrend EMA50                 │
              └────────────────┬─────────────────┘
                               │ (si tous passent)
                               ▼
              ┌──────────────────────────────────┐
              │   Position sizing Kelly Fractional│
              └────────────────┬─────────────────┘
                               │
                               ▼
              ┌──────────────────────────────────┐
              │   Exécution Binance API           │
              │   (si argent réel) OU Paper       │
              └────────────────┬─────────────────┘
                               │
                               ▼
              ┌──────────────────────────────────┐
              │   Audit trail JSON                │
              │   Notification Telegram           │
              └────────────────┬─────────────────┘
                               │
                               ▼
                       (à la sortie)
              ┌──────────────────────────────────┐
              │   Update Thompson Sampling        │
              │   Update Régime Memory            │
              │   Persiste en DB                  │
              └──────────────────────────────────┘
```

---

*v1.0 — 2026-04-25*
