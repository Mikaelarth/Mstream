# 03 — Agent Intelligent Évolutif (Pilier #2)

> Le bot **n'est pas une machine à règles fixes**. C'est un **agent qui
> apprend de ses trades** et devient **mesurablement meilleur** avec
> le temps.

---

## Principe fondamental

À chaque trade fermé (gagnant ou perdant), le bot :

1. **Mémorise** le résultat (PnL, R-multiple, conditions de marché,
   stratégie qui a voté pour ce trade).
2. **Met à jour** ses estimateurs de performance par stratégie et par
   régime de marché.
3. **Ajuste** automatiquement les poids des stratégies pour le prochain
   trade.
4. **Affiche** cette évolution à l'utilisateur (transparence).

Le bot n'est pas un "modèle pré-entraîné figé". C'est un **agent
adaptatif en ligne**.

---

## Algorithmes d'apprentissage utilisés (déjà codés)

### 1. **Thompson Sampling** sur les stratégies

Module : `core/adaptive.py:StrategyBandit`

**Idée** : pour chaque stratégie (trend follower, mean reversion,
breakout hunter), on maintient une **distribution Beta(α, β)** sur sa
probabilité de succès :
- α : nombre de victoires + 1 (prior)
- β : nombre de défaites + 1 (prior)

À chaque cycle, on **tire un échantillon** de chaque distribution.
La stratégie avec l'échantillon le plus élevé reçoit plus de poids
ce cycle-ci.

**Convergence** : après ~50 trades, la distribution converge sur la
vraie probabilité de succès → exploitation. Avant : exploration.

**Avantage** : équilibre automatique exploration / exploitation, sans
hyperparamètre.

### 2. **UCB1 (Upper Confidence Bound)** sur les profils paramétriques

Module : `core/adaptive.py:ParameterTuner`

**Idée** : différents "profils" de paramètres (par exemple :
agressif, équilibré, conservateur) sont testés. Le profil avec le
**meilleur ratio rendement / variance** est privilégié.

UCB1 ajoute un bonus d'exploration aux profils peu testés, garantissant
qu'aucun profil ne soit injustement abandonné.

### 3. **Mémoire de régime**

Module : `core/adaptive.py:RegimeMemory`

Chaque trade est tagué avec le **régime de marché** au moment de
l'entrée (Bull / Bear / Neutral). On peut ensuite mesurer :
- Quelle stratégie marche le mieux en Bull ?
- En Bear ?
- En Neutral ?

→ Permet de pondérer **conditionnellement** : "en Bear market, donner
moins de poids au trend follower".

### 4. **Persistance via DB**

Toutes les stats apprises sont **persistées en SQLite** (table
`strategy_performance`, `param_adjustments`, `regime_memory`).

→ Survit aux redémarrages : le bot n'oublie pas ce qu'il a appris.

---

## Architecture de l'apprentissage continu

```
┌────────────────────────────────────────────────┐
│         CYCLE TRADE NORMAL (60 min)            │
├────────────────────────────────────────────────┤
│  1. Fetch données marché                       │
│  2. Détecter régime (Bull/Bear/Neutral)        │
│  3. Calculer indicateurs                       │
│  4. Pour chaque stratégie : compute_score()    │
│  5. Vote pondéré ENSEMBLE (poids adaptatifs ←) │
│  6. Si signal qualifié : ouvre position        │
│  7. Trailing SL, gestion sortie                │
│  8. À la sortie : record_trade_outcome()  ──┐  │
└────────────────────────────────────────────────┘
                                              │
                                              ▼
┌────────────────────────────────────────────────┐
│        APPRENTISSAGE (déclenché par sortie)    │
├────────────────────────────────────────────────┤
│  9.  PnL et R-multiple calculés                │
│  10. Pour chaque stratégie qui avait voté      │
│      en faveur du trade, MAJ Beta(α, β)        │
│  11. Update RegimeMemory[regime, strategy]     │
│  12. Persiste en DB (idempotent)               │
│  13. Recalcule poids pour prochain cycle       │
└────────────────────────────────────────────────┘
```

---

## Visibilité utilisateur (l'écran "IA / Apprentissage")

C'est un **nouvel écran à créer** (cf. document 02). Il doit montrer :

### Bloc 1 — Performance par stratégie

| Stratégie | Trades | Win rate | R avg | Poids actuel | Poids initial |
|---|:-:|:-:|:-:|:-:|:-:|
| Trend Follower | 12 | 50 % | +0.4 | 1.2 | 1.0 |
| Mean Reversion | 8 | 38 % | -0.1 | 0.6 | 1.0 |
| Breakout Hunter | 5 | 60 % | +0.8 | 1.5 | 1.0 |

→ L'utilisateur voit que le bot a appris : Mean Reversion sous-
performe ici → poids réduit. Breakout sur-performe → poids augmenté.

### Bloc 2 — Mémoire par régime

| Régime | Stratégie dominante | Win rate | Trades en cumul |
|---|---|:-:|:-:|
| Bull | Trend Follower | 55 % | 18 |
| Neutral | Mean Reversion | 35 % | 4 |
| Bear | Aucune (skip) | – | 0 |

→ Le bot a appris que le mean reversion ne marche pas en bear, donc
il s'abstient.

### Bloc 3 — Évolution dans le temps

Graphique simple : ROI cumulé × temps, avec marqueurs des trades
(verts/rouges).

### Bloc 4 — Top 3 trades gagnants / perdants

Liste avec entry, exit, PnL, leçon apprise (ex: "Le breakout volume
faible a sous-performé → augmenter le seuil volume").

### Bloc 5 — État de la confiance

Indicateur global : "Le bot a 27 trades de mémoire — confiance
encore basse" / "47 trades — confiance moyenne" / "100+ trades —
confiance haute".

---

## Critères de succès de l'apprentissage

Pour démontrer que **le bot s'améliore vraiment** :

| # | Critère | Comment vérifier |
|:-:|---|---|
| 1 | Les poids des stratégies changent dans le temps | Graphique poids × temps non plat |
| 2 | Performance par régime cohérente avec littérature | Trend follower meilleur en Bull, mean reversion meilleur en range |
| 3 | Décroissance progressive du nombre de trades non profitables | Win rate ↗ après 50+ trades |
| 4 | Persistance survit aux redémarrages | Tuer app + relancer → poids inchangés |
| 5 | Le bot "skip" plus en bear market à mesure qu'il apprend | Comptage des skips par régime |

---

## Ce qui reste à faire (gap entre vision et code actuel)

✅ **Déjà codé** :
- `core/adaptive.py` (632 lignes) : StrategyBandit, ParameterTuner,
  RegimeMemory, AdaptiveAgent
- Tables DB : `strategy_performance`, `param_adjustments`,
  `regime_memory`
- 9 tests unitaires (`tests/test_adaptive.py`) : convergence Thompson,
  UCB, attribution

❌ **Pas encore connecté ou visible** :
1. **Pas d'écran UI** dédié à l'apprentissage. L'utilisateur ne voit
   pas que le bot évolue.
2. **L'intégration dans `auto_trader._cycle()` est partielle** :
   `record_trade_outcome` est appelé à la sortie, mais les poids
   adaptatifs ne sont pas systématiquement injectés dans
   `ensemble.vote(adaptive_weights=...)`.
3. **Pas de validation runtime** que les poids changent vraiment
   après des trades réels.

---

## Roadmap apprentissage continu

### Étape 1 — Connecter Thompson aux votes ensemble (priorité haute)

Vérifier que dans `auto_trader._compute_ensemble_vote`, les
`adaptive_weights = adaptive_agent.get_strategy_weights()` sont passés
à `ensemble.vote(adaptive_weights=...)`.

### Étape 2 — Créer l'écran IA / Apprentissage

Voir document 02. Affichage des 5 blocs ci-dessus.

### Étape 3 — Notifications "leçons apprises"

Telegram : "Le bot a noté que Mean Reversion sous-performe en bear.
Poids réduit de 1.0 à 0.6."

### Étape 4 — Validation A/B

Tourner 30 jours en réel **sans apprentissage** (poids fixes) puis
30 jours **avec apprentissage**. Mesurer la différence de ROI net.

Si l'apprentissage améliore la perf : ✅ pilier validé.
Si non : revoir l'algorithme.

---

## Garanties contre le sur-apprentissage

L'apprentissage en ligne est risqué : sur peu de trades, on peut
"croire" qu'une stratégie est mauvaise alors que c'était juste de la
malchance.

**Garde-fous obligatoires** :

1. **Prior fort** : Beta(α=1, β=1) au démarrage = on ne croit rien
   au début.
2. **Plancher de confiance** : pendant les 30 premiers trades,
   poids des stratégies bornés à [0.5, 2.0] de leur valeur initiale
   (pas de décision extrême sur peu de data).
3. **Régularisation** : à chaque update, on tire vers la moyenne
   (decay 0.95 par trade).
4. **Reset opt-in** : l'utilisateur peut **réinitialiser** la mémoire
   d'apprentissage si elle est devenue clairement aberrante.
5. **Hoeffding bounds** (cf. document 10, R11) : aucun update de
   poids n'est appliqué tant que la différence observée n'est pas
   statistiquement significative au seuil 95 %. Pas d'update sur le
   bruit.

---

## Au-delà du bandit : techniques avancées

Le bandit Thompson + UCB1 + RegimeMemory est notre **socle**, mais ce
n'est pas suffisant pour atteindre le niveau "le meilleur des
meilleurs". Le document **[10 — Innovations & Edge concurrentiel](10_INNOVATIONS_ET_EDGE.md)**
détaille les **12 lacunes structurelles du trading retail** et nos
**réponses concrètes** :

- **R1 — Calibration tracking** : nos confiances doivent être
  honnêtes (Brier score, ECE, reliability diagram)
- **R3 — Drift detection** : Page-Hinkley + ADWIN sur la série des
  R-multiples → détection silencieuse de la dégradation
- **R5 — Risque de queue** : Cornish-Fisher VaR + CVaR au lieu de la
  VaR Gaussienne aveugle aux black swans
- **R8 — Meta-gate** : un classifier "should we trade now ?" qui
  élimine l'overtrading dans le bruit (López de Prado, Meta-Labeling)
- **R10 — Mémoire long-terme** : table `learning_history` qui survit
  au-delà des positions ouvertes
- **R11 — Hoeffding bounds** : garantie statistique sur les updates

Chacune est implémentable en **pure Python**, mesurable, et
auditable. **Aucune fonctionnalité fictive.**

---

*v1.1 — 2026-04-25 — ajout référence doc 10*
