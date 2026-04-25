# 04 — Stratégies de Trading

> Le bot ne suit **pas une stratégie unique**. Il a **plusieurs
> stratégies indépendantes** qui votent, et le **vote pondéré
> évolue** selon ce que chaque stratégie a démontré (cf. doc 03).
>
> Il gère également **deux sous-portefeuilles** distincts :
> **Actif** (capital de travail) et **Réserve** (sécurisation
> progressive des bénéfices). Voir section dédiée plus bas.

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

## Architecture des portefeuilles : Actif / Réserve

> Politique de **skim profit adaptatif** : le bot transfère
> progressivement une partie de ses gains vers une Réserve sécurisée
> (USDT), pour que les profits accumulés ne soient pas remis à risque.
>
> *Cette politique est la v1 ; elle est destinée à évoluer en fonction
> du retour d'expérience.*

### Définitions

| Sous-portefeuille | Rôle | Forme | Localisation |
|---|---|---|---|
| **Actif** | Capital que le bot utilise pour trader (entrées, positions) | Cash + positions ouvertes | Compte spot Binance |
| **Réserve** | Capital sécurisé, soustrait du risque marché | **USDT uniquement** | Compte spot Binance (même compte, sous-compte logique géré par le bot) |
| **Capital total** | Actif + Réserve | mixte | – |

### Politique de skim adaptative (paliers de capital)

Le bot transfère vers la Réserve un pourcentage des **gains** réalisés
sur la **semaine écoulée**, selon le palier où le capital total se
situe par rapport au capital initial alloué.

**Paliers** (capital initial alloué = K0 ; ex : K0 = 20 USD) :

| Palier | Condition | % gains skim → Réserve |
|:-:|---|:-:|
| **P0 — Démarrage** | Capital total < 1.0 × K0 (encore en perte) | **0 %** (laisser le capital se reconstruire) |
| **P1 — Vert** | 1.0 × K0 ≤ Capital total < 1.2 × K0 (gain modeste) | **30 %** |
| **P2 — Croissance** | 1.2 × K0 ≤ Capital total < 2.0 × K0 (gain confirmé) | **50 %** |
| **P3 — Doublement** | 2.0 × K0 ≤ Capital total < 5.0 × K0 | **70 %** |
| **P4 — Excellence** | Capital total ≥ 5.0 × K0 | **80 %** |

**Logique** : tant que le bot n'a pas prouvé qu'il sait gagner (P0),
on lui laisse 100 % du capital pour qu'il puisse exister. À mesure
qu'il gagne, on sécurise de plus en plus.

### Cycle de skim : hebdomadaire

- **Quand** : chaque dimanche à 23:00 UTC (cycle propre, hors heures
  de marché crypto les plus volatiles)
- **Calcul** :
  - `actif_courant` = solde USDT libre Actif + valeur positions ouvertes
  - `gains_semaine` = `actif_courant` - `actif_lundi_dernier` - `pertes_semaine`
  - Si `gains_semaine > 0` : transfert = `gains_semaine × % skim du palier`
  - Sinon : pas de transfert
- **Action** : le bot exécute un transfert interne USDT
  Actif → Réserve via le journal d'audit (pas un trade Binance, juste
  un déplacement comptable dans la DB locale + tracking sur Binance)

### Rebalancing exceptionnel : Réserve → Actif

Le bot **peut** puiser dans la Réserve, mais sous **conditions strictes** :

1. L'Actif est descendu **sous 50 % de K0** (perte sévère)
2. La Réserve dispose d'**au moins K0** disponible
3. Une **opportunité de marché à haute confiance** est détectée
   (signal STRONG_BUY confluence MTF + ensemble unanime)
4. Pas de rebalancing fait depuis ≥ 30 jours

Si toutes les conditions sont remplies :
- Transfert maximum = **30 %** de la Réserve disponible
- **Audit obligatoire** dans `audit_log` avec `event_type = "REBALANCE_RESERVE_TO_ACTIVE"`
- **Notification Telegram** au user (information, pas demande
  d'autorisation — autonomie totale)

### Verrouillage côté UI (politique v1)

L'utilisateur **ne peut pas retirer la Réserve via l'app**. Pour
récupérer cette Réserve :
- Soit accepter qu'elle tourne dans la croissance composée du bot
- Soit aller **directement sur Binance** (web ou app officielle) pour
  retirer les USDT de son compte

L'**Actif** reste retirable via l'app (mais avec confirmation
double-tap si retrait > 50 % de l'Actif).

**Justification de cette asymétrie** : éviter que l'utilisateur, dans
un moment de stress (krach marché, peur), vide la Réserve et annule
tous les bénéfices de la stratégie. Si on laisse la Réserve sur
Binance directement, ajouter une étape volontaire est un garde-fou
psychologique.

> Cette politique évoluera (cf. Q5 user). Possibles évolutions :
> - Ajouter un bouton "Récupérer ma Réserve" avec délai 24h + 2FA
> - Permettre à l'utilisateur de définir lui-même son taux de skim
> - Ajouter un mode "vacances" qui passe tout en Réserve

### Affichage UX (côté `02_EXPERIENCE_UTILISATEUR.md`)

L'écran Portfolio doit montrer **les deux sous-portefeuilles** côte
à côte :

```
┌──────────────────────────────────────────────┐
│  PORTFOLIO                                   │
├──────────────────────────────────────────────┤
│  Capital total : $24.30  (+21.5% vs initial) │
│                                              │
│  ┌─────────────────┐  ┌─────────────────┐   │
│  │   🔵 ACTIF       │  │  🟢 RÉSERVE      │   │
│  │   $18.50         │  │  $5.80          │   │
│  │   Actif Bot      │  │  Verrouillée    │   │
│  │   en mouvement   │  │  Bénéfices skim │   │
│  └─────────────────┘  └─────────────────┘   │
│                                              │
│  Palier actif : P2 — Croissance              │
│  Skim hebdo : 50% des gains                 │
│  Prochain skim : Dimanche 23:00              │
│                                              │
│  Positions ouvertes : 1                      │
│  ...                                         │
└──────────────────────────────────────────────┘
```

### Implémentation technique

Module à créer/étendre : `core/wallet_manager.py`

```python
class WalletManager:
    """Gère la séparation Actif / Réserve et les flux de skim."""

    def get_active_balance(self) -> float: ...
    def get_reserve_balance(self) -> float: ...
    def get_total_capital(self) -> float: ...
    def get_palier(self) -> str: ...   # "P0".."P4"
    def get_skim_pct(self) -> float: ...

    def perform_weekly_skim(self) -> dict: ...
    """Calcule gains semaine et déverse selon palier. Idempotent."""

    def maybe_rebalance_reserve_to_active(self) -> dict | None: ...
    """Vérifie les conditions, exécute si OK, audit obligatoire."""
```

Tables DB nouvelles :
- `wallet_snapshots` : snapshot quotidien Actif/Réserve/total/palier
- `skim_history` : historique des transferts hebdomadaires
- `rebalance_history` : historique des rebalances exceptionnels

---

## Cold-start protocol (les 30 premiers jours en réel)

Avec **20 USD et 0 trade live**, le bot ne peut pas utiliser un Kelly
"plein" — il n'a aucune evidence statistique de son edge réel. Tous les
backtest, walk-forward, et critères de R/R supposent que la distribution
historique reste valide. **Le cold-start protocol force la prudence
bayésienne**.

### Règle du scaling progressif

| Phase | Trades cumulés | Position size | Règle de validation pour passer à la phase suivante |
|:-:|:-:|:-:|---|
| **P0 — Probation** | 0 → 10 | **30 % du Kelly** capé à 1 USD | ≥ 60 % des trades sans erreur d'exécution + 0 anomalie data |
| **P1 — Apprentissage** | 11 → 30 | **50 % du Kelly** capé à 2 USD | Expectancy estimée IC 95 % **exclut zéro** vers le haut |
| **P2 — Confiance** | 31 → 100 | **75 % du Kelly** capé à 5 USD | Sharpe live ≥ 50 % du Sharpe walk-forward champion |
| **P3 — Régime nominal** | 100+ | **Kelly fractionnel complet** (1/4 Kelly) | — |

### Conditions de rétrogradation

À tout moment, si :
- 3 SL consécutifs **dans la phase courante** → retour à la phase
  précédente (-1)
- Drawdown > 15 % du capital initial → retour P0 forcé + notification
- Drift détecté (cf. doc 10, R3) → maintien de la phase courante (pas
  de promotion tant que le drift n'est pas résolu)

### Garanties statistiques

**Le passage de phase n'est jamais automatique sur compteur de trades
seul**. Il exige **les deux** :
1. Le seuil quantitatif (10 trades / 30 trades / 100 trades)
2. La condition de validation associée (expectancy IC, Sharpe, etc.)

→ Un bot qui a fait 30 trades mais dont l'expectancy IC contient zéro
**reste en P1**, même si "30 trades" est atteint.

### Plancher d'exécution

**Binance min order ≈ 5 USD pour BTC/ETH**. Si la phase impose un cap
< min order, on **skip le trade** plutôt que de violer la règle de cap.
Mieux vaut moins de trades en cold-start que des trades sur-dimensionnés.

### Affichage utilisateur

Dans l'écran "État du bot" (doc 02), un bandeau permanent affiche :

```
🟡 Phase apprentissage P1 (trade 14/30)
   Position size : 50 % du Kelly · cap 2 USD
   Promotion P2 si : expectancy IC > 0 (actuel : −0.05 .. +0.32)
```

→ L'utilisateur **voit** que le bot est encore en mode prudent, et
comprend pourquoi les positions sont petites au début.

### Critères mesurables (CS1-CS4)

| # | Critère | Validation |
|:-:|---|---|
| CS1 | Aucun trade > cap de phase courante | audit trail |
| CS2 | Promotion uniquement si seuil + condition validation | audit trail |
| CS3 | Rétrogradation effective ≤ 1 cycle après déclenchement | audit trail |
| CS4 | Bandeau phase visible en permanence dans l'app | inspection UI |

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
