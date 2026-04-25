# Backtesting — Valider la stratégie avant le réel

## Pourquoi backtester ?

Aucune stratégie de trading ne devrait être lancée en production sans avoir été **validée sur données historiques**. Le backtesting permet de répondre aux questions critiques :

- Est-ce que cette stratégie aurait gagné de l'argent sur les 3 derniers mois ?
- Quelle est le pire drawdown historique ?
- Combien de trades par mois en moyenne ?
- Quel est le Sharpe ratio ? Le profit factor ?
- Les seuils (score 55, R/R 2.5) sont-ils optimaux ?

MstreamTrader embarque un moteur de backtesting **cohérent à 100 % avec le Bot Maître réel** — mêmes règles, même scoring, même trailing SL, même protection drawdown.

---

## Les 3 outils de validation

MstreamTrader fournit **trois niveaux** de validation, du plus simple au plus rigoureux :

| Outil | Fichier | Objectif |
|---|---|---|
| **Backtest simple** | `run_backtest.py` | Teste UNE configuration sur une période donnée |
| **Grid Search** | `optimize_params.py` | Teste ~80 combinaisons de paramètres |
| **Walk-Forward** | `optimize_params.py --walk-forward` | **Valide la robustesse hors-sample** (gold standard) |

La règle d'or : **ne jamais déployer en réel sans walk-forward positif**.

---

## Démarrage rapide

### Backtest par défaut (90 jours, tous les coins, $1 000)

```bash
cd MstreamTrader
python run_backtest.py
```

### Backtest personnalisé

```bash
# 30 jours, $5 000 initial, seulement BTC et ETH
python run_backtest.py --days 30 --capital 5000 --coins bitcoin,ethereum

# Plus agressif : risque 8%, max 6 positions
python run_backtest.py --risk 8 --max-positions 6

# Filtre plus strict : score ≥ 65, R/R ≥ 3.0
python run_backtest.py --min-score 65 --min-rr 3.0

# Afficher le détail de chaque trade
python run_backtest.py --verbose

# Sauvegarder le résultat complet en JSON
python run_backtest.py --save backtest_result.json
```

---

## Comprendre le rapport

Exemple de sortie :

```
═════════════════════════════════════════════════════════════
              RAPPORT DE BACKTEST — Bot Maître              
═════════════════════════════════════════════════════════════

  CAPITAL
    Initial         :   $    1,000.00
    Final           :   $    1,147.82
    Rendement total :        +14.78 %
    Rendement annu. :        +72.45 %

  RISQUE
    Max Drawdown    :         8.34 %   [ACCEPTABLE]
    Durée max DD    :         18 bougies

  RATIOS RISK-ADJUSTED
    Sharpe Ratio    :        1.823   [BON]
    Sortino Ratio   :        2.914   [BON]
    Calmar Ratio    :        8.685   [BON]

  TRADES
    Total           :         23
    Gagnants        :         14  (60.9 %)
    Perdants        :          9
    Profit Factor   :        1.842   [RENTABLE]
    Expectancy      :  $    +6.43  / trade

  STATISTIQUES TRADES
    Gain moyen      :  $   +18.94
    Perte moyenne   :  $   -13.52
    Meilleur trade  :  $   +42.15
    Pire trade      :  $   -22.80

  R-MULTIPLES (P&L / risque initial)
    R moyen         :       +0.314   [POSITIF]
    R médian        :       +0.250
    R meilleur      :       +2.100
    R pire          :       -1.000
═════════════════════════════════════════════════════════════
```

### Les métriques clés expliquées

| Métrique | Signification | Valeur cible |
|---|---|---|
| **Rendement annualisé** | Croissance projetée sur 1 an | > 20 % en crypto est bon |
| **Max Drawdown** | Pire chute depuis un sommet | < 15 % = acceptable, > 25 % = dangereux |
| **Sharpe Ratio** | Rendement par unité de volatilité | > 1 bon, > 2 excellent, > 3 exceptionnel |
| **Sortino Ratio** | Comme Sharpe, mais ne pénalise que la volatilité négative | > 1.5 bon |
| **Calmar Ratio** | Rendement annualisé / Max DD | > 1 acceptable, > 3 excellent |
| **Profit Factor** | Σ gains / Σ pertes | > 1.0 rentable, > 1.5 bon, > 2.0 excellent |
| **Expectancy** | Gain moyen attendu par trade | Doit être > 0 |
| **R-multiple moyen** | P&L moyen ÷ risque initial | > 0.3 = stratégie viable |

### Comment juger une stratégie ?

Une stratégie **déployable en production** doit vérifier **toutes** ces conditions :

✅ Rendement annualisé > 20 %
✅ Max Drawdown < 20 %
✅ Sharpe > 1.0
✅ Profit Factor > 1.3
✅ R-multiple moyen > 0.2
✅ Au moins 30 trades (échantillon statistique suffisant)

Si une condition n'est pas remplie → **ne pas déployer en réel**. Ajuster les paramètres et re-backtester.

---

## Méthodologie du backtest

### 1. Source des données
CoinGecko API `/coins/{id}/ohlc?days={days}`. Granularité automatique :
- ≤ 1 jour → bougies 30 min
- ≤ 90 jours → bougies 4 heures (recommandé)
- > 90 jours → bougies 4 jours (coarse, moins précis)

### 2. Alignement multi-coins
Les timestamps sont **intersectés** entre tous les coins — seules les bougies présentes partout sont simulées. Évite les décalages temporels.

### 3. Warmup period
Les **60 premières bougies** ne génèrent pas de trades. Les indicateurs techniques (EMA 50, MACD 26) ont besoin d'un historique suffisant pour être stables.

### 4. Exécution intra-candle
Pour détecter si SL ou TP a été touché pendant une bougie :
- On vérifie `candle.low ≤ stop_loss` → SL touché (ordre pessimiste)
- Sinon `candle.high ≥ take_profit` → TP touché
- **Ordre conservateur** : SL testé AVANT le TP dans le cas rare où les deux auraient pu être touchés dans la même bougie

### 5. Coûts modélisés
- **Frais** : 0.1 % par transaction (Binance standard, paramétrable via `--fee`)
- **Slippage** : 0.05 % par transaction (paramétrable via `--slippage`)
- À l'entrée : prix d'exécution = `signal_price × (1 + slippage)`
- À la sortie : prix d'exécution = `exit_price × (1 − slippage)`

### 6. Capital composé
Les profits sont réinvestis immédiatement — chaque nouveau trade dimensionne sa position selon le capital total courant (`capital + invested`), pas le capital initial.

### 7. Protection drawdown
Si la valeur totale du portefeuille tombe sous `peak × (1 − 20%)`, les nouvelles entrées sont bloquées jusqu'à ce que le drawdown se résorbe. Les positions ouvertes restent surveillées (SL/TP).

---

## Optimiser les paramètres

### Grid search manuel

Testez plusieurs combinaisons pour trouver l'optimum :

```bash
# Comparer différents niveaux de risque
for risk in 2 3 5 7 10; do
    echo "=== Risk: ${risk}% ==="
    python run_backtest.py --risk $risk --save result_risk_${risk}.json
done
```

### Paramètres à explorer

| Paramètre | Plage recommandée | Remarque |
|---|---|---|
| `--risk` | 1 à 10 % | Plus élevé = + de volatilité |
| `--max-positions` | 2 à 8 | Trop haut = corrélation |
| `--min-score` | 40 à 70 | Plus haut = moins de trades mais plus sélectifs |
| `--min-rr` | 1.5 à 4.0 | Plus haut = filtres beaucoup de trades |
| `--days` | 60 à 180 | Plus de jours = échantillon statistique plus fiable |

---

## Exemple d'analyse de résultats

Scénario : après avoir testé `--risk 5 --min-score 55 --min-rr 2.5` sur 90 jours :

- **Résultat** : +14.78 % (soit ~72 % annualisé)
- **Max DD** : 8.34 % — confortable
- **23 trades** en 90 jours — bon rythme (un trade tous les ~4 jours)
- **Win rate** : 60.9 % — au-dessus de la moyenne (les stratégies techniques sont entre 40 et 55 %)
- **Profit factor** : 1.84 — rentabilité nette décente

**Conclusion** : stratégie **validée** pour déploiement en réel avec un capital de départ modéré.

Si on avait eu :
- Max DD > 25 %
- Profit factor < 1.2
- Moins de 10 trades

→ Ajuster les paramètres et re-backtester avant tout déploiement.

---

## Limites connues

1. **CoinGecko free tier** limite à 30 requêtes/minute — télécharger 8 coins peut prendre 20-30 s
2. **Granularité 4h** n'est pas idéale pour scalping mais parfaite pour la stratégie swing actuelle
3. **Pas de simulation de funding rate** (non applicable en spot)
4. **Volumes non pris en compte** — un gros ordre pourrait subir plus de slippage qu'estimé
5. **Backtest ≠ Forward test** : performance passée ne garantit pas le futur. Toujours commencer en **paper mode** sur le réel avant de mettre de l'argent.

---

## 🎯 Grid Search d'optimisation

Le script [optimize_params.py](../MstreamTrader/optimize_params.py) teste **systématiquement** toutes les combinaisons d'un jeu de paramètres et les classe par **score composite** multi-critères.

### Grille par défaut

```python
DEFAULT_GRID = {
    "min_score":     [45, 50, 55, 60, 65],
    "min_rr":        [2.0, 2.5, 3.0, 3.5],
    "risk_pct":      [2.0, 3.5, 5.0, 7.5],
    "max_positions": [3, 4, 5],
}
# 5 × 4 × 4 × 3 = 240 combinaisons
```

### Score composite

```
quality_score = (Sharpe × PF_capped × √(trades/30))
               − (max_drawdown × 0.05)
               + bonus si annualized_return > 30%
               − malus si win_rate < 25%
               − malus si trades < 5
```

Une configuration est **déployable** si tous les critères suivants sont remplis :
- total_trades ≥ 15
- Sharpe > 0.8
- Profit Factor > 1.3
- Max DD < 25 %
- Win rate > 35 %

### Usage

```bash
# Grid search standard (sans régime)
python optimize_params.py --days 60

# Avec filtre de régime
python optimize_params.py --days 60 --regime

# Sauvegarde des résultats JSON
python optimize_params.py --days 60 --save best.json
```

---

## 🏆 Walk-Forward Analysis (gold standard)

### Le problème du backtest simple

Un backtest classique sur UNE période peut être **overfit** — les paramètres ont été, par chance, optimaux pour cette période passée. Rien ne garantit que la stratégie fonctionnera sur les périodes suivantes.

**Walk-Forward** résout ce problème en découpant l'historique en **fenêtres glissantes** et en mesurant la performance **hors du training set**.

### Méthode

```
Exemple avec 120 jours, window=60, step=30 :

j0 ────────────── j60 ────── j90 ────── j120
│   Fenêtre 1                │
│   [train 0-42|test 42-60]  │          ← OOS
│                            │
│          Fenêtre 2                    │
│          [train 30-72|test 72-90]     ← OOS
│                                       │
│                    Fenêtre 3          │
│                    [train 60-102|test 102-120]  ← OOS

→ On n'évalue QUE les périodes "test" (hors training)
→ Agrégation = moyenne des OOS
```

### Critères de ROBUSTESSE

Une stratégie est déclarée **robuste** uniquement si :
- ✅ **Consistency > 60 %** (au moins 60 % des fenêtres finissent en gain)
- ✅ **Sharpe moyen > 0.5**
- ✅ **Profit Factor moyen > 1.2**

Si **TOUS** ces critères sont remplis, `is_robust = True` dans le résultat.

### Usage

```bash
# Walk-forward avec fenêtres de 30 jours, step de 10
python optimize_params.py --days 120 --walk-forward --wf-window 30 --wf-step 10

# Avec filtre régime (recommandé)
python optimize_params.py --days 180 --walk-forward --regime --top 10
```

Bonus **+1.0** au quality_score si une configuration est robuste via walk-forward. Permet de différencier les vraies stratégies des chanceuses.

### Exemple de sortie

```
Grid search (WALK-FORWARD) : 240 combinaisons à tester...
  5 min_score × 4 min_rr × 4 risk_pct × 3 max_positions
  Fenêtres walk-forward : 30j (step 10j)

    1/240 [V] ROB score=+6.23 ret_avg=+4.12% Sh= 1.85 PF= 1.92 DD_avg= 4.21% cons= 80.0% trades=  45 wins=5
    2/240 [x] ROB score=+5.84 ret_avg=+3.87% Sh= 1.72 PF= 1.76 DD_avg= 5.45% cons= 75.0% trades=  38 wins=5
    3/240 [V] ROB score=+5.21 ret_avg=+3.22% Sh= 1.61 PF= 1.68 DD_avg= 3.98% cons= 66.7% trades=  52 wins=5
    ...

============================================================
 TOP 10 CONFIGURATIONS PAR QUALITY SCORE
============================================================
   1  +6.23  VRAI  score=55 rr=3.0 risk=5% pos=4 ret=+4.12% Sh=1.85 trades= 45
   2  +5.84  VRAI  score=60 rr=2.5 risk=3% pos=3 ret=+3.87% Sh=1.72 trades= 38
   3  +5.21  VRAI  score=50 rr=3.0 risk=5% pos=4 ret=+3.22% Sh=1.61 trades= 52
   ...
```

Les lignes `[V] ROB` sont **déployables et robustes**. Les `[x]` ne remplissent pas tous les critères.

---

## API programmatique

Pour intégrer le backtest dans un script Python :

```python
from core.backtest import Backtest, BacktestConfig
from core.market_data import get_historical_prices

# Configurer
config = BacktestConfig(
    initial_capital=2000.0,
    risk_pct=5.0,
    min_score=55.0,
    min_rr=2.5,
)

# Charger les données
coins_data = {
    "bitcoin":  get_historical_prices("bitcoin",  days=90),
    "ethereum": get_historical_prices("ethereum", days=90),
    "solana":   get_historical_prices("solana",   days=90),
}

# Exécuter
bt = Backtest(config)
result = bt.run(coins_data)

# Accès aux données
print(f"Rendement : {result.report['total_return_pct']}%")
print(f"Sharpe    : {result.report['sharpe']}")
print(f"Trades    : {len(result.trades)}")

# Courbe d'équité (pour graph matplotlib par exemple)
equity = result.equity_curve
```
