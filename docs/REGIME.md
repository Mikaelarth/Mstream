# Filtre de Régime de Marché

## Le problème

Un bot qui applique les mêmes règles en bull market et en bear market se fait laminer. Les signaux techniques ont une fiabilité très différente selon le contexte macro :

- **Bull market** : `RSI < 30` = opportunité d'achat (rebond probable)
- **Bear market** : `RSI < 30` = "falling knife" (le prix continue de chuter)

Sans filtre de régime, le Bot Maître achète des supports cassés en bear market et se fait stopper en cascade.

## La solution

MstreamTrader embarque un détecteur de régime basé sur **BTC vs EMA 200 daily**. Selon le régime détecté, les seuils d'entrée du bot s'adaptent automatiquement.

### Pourquoi BTC ?
Les 8 cryptos suivies sont corrélées à BTC entre 80 % et 95 % sur 24h. Le régime de BTC définit le régime du marché crypto dans son ensemble. Ça ne sert à rien d'avoir un filtre par coin : ils montent et descendent ensemble.

### Pourquoi EMA 200 daily ?
C'est la moyenne mobile institutionnelle de référence, utilisée par la majorité des traders pros comme niveau de bascule bull/bear. Stable, lente, peu sensible au bruit.

## Les trois régimes

| Régime | Condition | Ce que ça signifie |
|---|---|---|
| 🟢 **BULL** | BTC > EMA 200 + 2 % | Tendance haussière établie |
| 🟡 **NEUTRAL** | BTC dans ±2 % de EMA 200 | Range / transition |
| 🔴 **BEAR** | BTC < EMA 200 − 2 % | Tendance baissière établie |

La zone de tolérance de ±2 % évite les bascules intempestives quand le prix oscille autour de l'EMA.

## Profils adaptatifs appliqués par le Bot Maître

Chaque régime déclenche un **profil de paramètres différent** :

| Paramètre | 🟢 BULL | 🟡 NEUTRAL | 🔴 BEAR |
|---|---:|---:|---:|
| Score minimum | 55 | 60 | **70** |
| Confiance minimum | 65 % | 70 % | **75 %** |
| Ratio R/R minimum | 2.5 | 3.0 | **3.5** |
| Risque par trade | 5 % | 3.5 % | **2 %** |
| Max positions | 4 | 3 | **2** |
| Max capital investi | 80 % | 60 % | **40 %** |

### Logique des profils

**🟢 BULL** — Tolérance aux trades plus agressive
> Le marché monte, les signaux BUY sont fiables. Le bot peut prendre plus de positions avec un risque plus élevé.

**🟡 NEUTRAL** — Prudence élevée
> Incertitude directionnelle. Le bot exige des signaux plus propres (score 60+, R/R 3.0+), réduit son exposition.

**🔴 BEAR** — Défense maximale
> Les signaux BUY sont des pièges à 60-70 %. Le bot ne trade que les signaux exceptionnels (score 70+), avec un risque divisé par 2.5 et max 2 positions.

## Activation

### Dans le backtest

```bash
# Sans filtre (seuils fixes, comportement d'origine)
python run_backtest.py --days 90

# Avec filtre de régime
python run_backtest.py --days 90 --regime
```

Le rapport final affiche la **répartition par régime** :
```
  RÉPARTITION PAR RÉGIME DE MARCHÉ
    bull     :  380 bougies (62.3%)   18 trades
    neutral  :  145 bougies (23.8%)    3 trades
    bear     :   85 bougies (13.9%)    1 trade
```

### Dans le Bot Maître live

Le filtre est activé **automatiquement** dans [core/auto_trader.py](../MstreamTrader/core/auto_trader.py). Dès le lancement, le bot :
1. Détecte le régime courant via Binance public klines (BTC daily, 300 bougies)
2. Cache le résultat pour 6 h
3. Applique le profil adapté à chaque cycle d'analyse
4. Affiche le régime courant dans son statut : `BOT MAITRE ACTIF [BULL] | Capital: $1,247...`

## Limites connues

### Faux signaux de régime
Autour de la frontière (BTC ±2 % de EMA 200), le régime peut basculer plusieurs fois par semaine. Ce n'est pas un bug — c'est la réalité des marchés en transition. Le bot garde la dernière détection en cache 6 h pour lisser.

### Historique requis
Il faut au moins **200 bougies daily** pour calculer l'EMA 200. Si un coin vient d'être listé, impossible de détecter son régime. Pour les 8 cryptos majeures suivies (BTC, ETH, BNB, SOL, XRP, ADA, DOGE, DOT), ce n'est jamais un problème.

### Pas de régime intra-day
Le régime est calculé en daily. Un micro-krach de quelques heures peut ne pas faire basculer. Pour du trading haute fréquence (pas l'objectif de MstreamTrader), il faudrait des régimes plus réactifs.

### Corrélation : pas toujours 100 %
Certains alts (ADA, DOT historiquement) peuvent bouger à contre-tendance de BTC sur quelques jours. Le filtre BTC reste globalement pertinent mais imparfait.

## Optimisation

Le script [optimize_params.py](../MstreamTrader/optimize_params.py) permet de tester systématiquement avec et sans filtre :

```bash
# Grid search sans régime
python optimize_params.py --days 60

# Grid search avec régime (utilise les profils adaptatifs comme base)
python optimize_params.py --days 60 --regime
```

Vous pouvez alors comparer les deux meilleures configurations pour voir si le filtre de régime **améliore effectivement** la stratégie sur votre période de test.

## Détection de Transition (Early Signal)

Au-delà de la simple détection du régime courant, MstreamTrader détecte les **bascules imminentes** via `detect_regime_transition()` dans [core/regime.py](../MstreamTrader/core/regime.py).

### Signaux détectés

1. **Golden Cross / Death Cross** — EMA 50 croise EMA 200 sur les données daily
2. **Momentum fort** — Prix gagne/perd > 5 % vs EMA 200 en 10 jours
3. **Slope EMA 200 inverse** — la moyenne long-terme elle-même change de direction (> 2 % sur 10j)
4. **Prix proche de la frontière** — oscillations autour de ±2 % de l'EMA 200

### Output

```python
{
    "transitioning":     True,
    "from_regime":       "bear",
    "to_regime":         "neutral",
    "transition_score":  0.73,        # 0 à 1
    "signals":           ["Golden Cross il y a 4j", "Momentum haussier +7.2%"],
    "days_to_bascule":   3,           # estimation (peut être None)
    "btc_deviation_pct": -1.85,
}
```

### Blending dans le Bot Maître

Quand `transition_score >= 0.5`, le bot **mélange** le profil courant et le profil cible :

```python
profile = {
    k: (profile_current[k] + profile_target[k]) / 2
    for k in profile_current
}
```

**Effet concret** : si on est en BEAR mais qu'une transition vers NEUTRAL est détectée avec score 0.7, les seuils d'entrée deviennent (BEAR + NEUTRAL) / 2 → plus permissifs. Permet au bot de **commencer à se repositionner AVANT** que la bascule officielle ne survienne.

---

## Personnalisation des profils

Pour ajuster les profils, éditer [core/regime.py](../MstreamTrader/core/regime.py) :

```python
REGIME_PROFILES = {
    Regime.BULL: {
        "min_score":      55.0,   # ← personnaliser
        "min_confidence": 65.0,
        "min_rr":         2.5,
        "risk_pct":       5.0,
        "max_positions":  4,
        "max_capital_pct": 80.0,
    },
    # ...
}
```

Ré-exécuter le backtest après modification pour valider l'impact.
