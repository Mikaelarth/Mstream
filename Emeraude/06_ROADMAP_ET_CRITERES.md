# 06 — Roadmap et Critères de Terminaison

> Le projet avance par **paliers de validation**. Chaque palier a des
> conditions de passage **mesurables**. On ne passe pas au palier
> suivant sans avoir validé le précédent.

---

## Schéma global

```
  P0           P1            P2            P3            P4            P5            P6
  ──           ──            ──            ──            ──            ──            ──
  État    →  Trading    →  Stabili-  →  Calibra-  →  Sécurité  →  Crois-     →  Niveau
  courant    réel          sation       tion         produc-       sance         entreprise
             20 USD        30 jours     alpha        tion          capital       validé
                                                                                  (6-12 mois)
```

Chaque palier ajoute des features **et** des critères mesurables.
Le palier "Niveau Entreprise" (P6) est l'objectif final : engagement
chiffré sur SLA, sécurité hardware-backed, autonomie utilisateur
totale.

---

## Palier 0 — État courant (24/04/2026)

### Ce qui marche

✅ **Code source** : 28 modules, 311 tests pytest verts, CI verte
✅ **App desktop** : se lance sans crash, UI fonctionnelle
✅ **APK Android** : compile via CI, s'installe, démarre
✅ **Sécurité clés API** : chiffrées, masquées au reload UI
✅ **Confirmation argent réel** : double-tap obligatoire
✅ **Bornes max budgets** : 10M USD plafond
✅ **Audit trail** : JSON queryable 30 jours rétention
✅ **Backup DB** : create + restore atomique testés (5 tests)
✅ **Walk-forward champion** : Sharpe avg +0.93, PF 3.03, 4/10 fenêtres

### Ce qui manque

🔴 **Test runtime user** : APK n'a jamais tourné > 1h sur smartphone
🔴 **Connexion Binance** : codée et SSL fixé mais jamais validée user
🔴 **Persistance Android** : code en place mais jamais testée user
🔴 **Paper mode 30 jours** : jamais lancé
🔴 **Trading réel** : jamais effectué
🔴 **Notifications Telegram** : codées, user pas accès au compte
🔴 **Walk-forward consistency** : 40 % (seuil = 50 %)
🔴 **Écran IA / Apprentissage** : pas créé
🔴 **Adaptive ↔ Ensemble vote** : intégration partielle à valider

---

## Palier 1 — Trading réel sur 20 USD

### Objectif

Lancer le bot en argent réel avec 20 USD sur Binance et le laisser
tourner.

### Conditions de passage (toutes ✅ obligatoires)

| # | Condition | Mesure | Statut |
|:-:|---|---|:-:|
| P1.1 | App tourne sans crash 1h sur Android | Test user | 🔴 |
| P1.2 | Persistance survit redémarrage Android | Tuer/relancer app, valeurs intactes | 🔴 |
| P1.3 | Connexion Binance fonctionne | Solde réel récupéré côté user | 🔴 |
| P1.4 | Paper mode tourne 1h sans bug | User test | 🔴 |
| P1.5 | Backtest UI produit un rapport lisible | User test | ✅ |
| P1.6 | Walk-forward Sharpe avg ≥ 0.5 | Mesure code | ✅ +0.93 |
| P1.7 | Walk-forward PF avg ≥ 1.2 | Mesure code | ✅ 3.03 |
| P1.8 | Toggle Bot Maître exige confirmation argent réel | Code review | ✅ |

### Actions à mener

1. **User côté smartphone** :
   - Désinstaller ancien APK si présent
   - Installer nouvel APK depuis GitHub Actions
   - Configurer clés API Binance (READ + TRADE, pas WITHDRAW)
   - Activer Paper Mode + budget 100 USD virtuel
   - Laisser tourner 1h, vérifier qu'il y a des cycles
   - Valider persistance : tuer app, relancer, configs intactes

2. **Si tout OK** :
   - Désactiver Paper Mode
   - Configurer Bot Maître budget = 20 USD
   - Activer le switch (double-tap confirmation argent réel)
   - Le bot trade automatiquement

### Critères de succès du palier

- ✅ Au moins 1 trade réel exécuté dans les 7 jours
- ✅ Aucun crash app pendant la période
- ✅ Audit trail contient le trade

### Critères d'échec / rollback

- 🔴 App crash > 3× / 24h → désactiver bot, retourner palier 0
- 🔴 Drawdown > 30 % en 24h → désactiver bot, audit
- 🔴 Bug perte de données → désactiver bot, fix

---

## Palier 2 — Stabilisation 30 jours

### Objectif

Le bot tourne pendant 30 jours en argent réel. On collecte de la
data et on mesure objectivement.

### Conditions de passage du palier (toutes ✅)

| # | Condition | Mesure | Cible |
|:-:|---|---|---|
| P2.1 | ROI net après frais | (capital_final - 20) / 20 | **≥ 0 %** (= ne perd pas) |
| P2.2 | Nombre de trades exécutés | Audit trail | **≥ 5** |
| P2.3 | Drawdown max sur la période | (peak - bottom) / peak | **< 20 %** |
| P2.4 | Crashes app | Logs | **0** |
| P2.5 | Fuites de clé API | Audit code + UI | **0** |
| P2.6 | Persistance maintenue | Vérification weekly | **100 %** |

### Actions automatiques (le bot le fait tout seul)

- Cycle 60 min : analyse + décision
- Logs rotatifs quotidiens
- Backup DB tous les 24 cycles
- Health check chaque cycle
- Audit purge > 30 jours
- Snapshot capital quotidien (`equity_history`)

### Actions utilisateur

- Vérifier l'app **1×/jour** (matin ou soir, < 2 min)
- Lire le journal des décisions du bot
- Vérifier qu'aucune alerte critique n'apparaît
- En cas d'anomalie, capture + report dev

### Critères de succès du palier

- Au moins 5 trades exécutés
- ROI net ≥ 0 % (objectif minimal : ne pas perdre)
- ROI **bonus** : ≥ +1 % par mois (= ~12 % annuel, conservateur)
- Le bot a alimenté la mémoire d'apprentissage (Thompson Sampling
  a évolué)

### Critères d'échec / rollback

- 🔴 Drawdown > 20 % à un moment quelconque → Circuit breaker
  s'active automatiquement, on désactive et audit
- 🔴 Bot ne prend aucun trade pendant 14 jours consécutifs → revoir
  filtres
- 🔴 ROI < -10 % à 30 jours → arrêter, retour palier 1, refonte algo

---

## Palier 3 — Calibration alpha

### Objectif

Améliorer la performance pour atteindre Sharpe walk-forward > 1.0
et consistency > 60 %.

### Pré-requis

- Palier 2 réussi (au moins 30 jours de data réelle)

### Travaux à mener (par ordre d'impact estimé)

#### 3.1 Écran "IA / Apprentissage" (cf. doc 03)

Créer le 5ème écran qui montre comment le bot évolue. **Sans cet
écran, l'utilisateur ne voit pas l'apprentissage** = défaut UX
critique.

**Effort** : ~3-4 jours

#### 3.2 Refonte scoring `signals.py`

Rebalancer les pondérations actuelles :
- RSI × 1.0 (trop fort, noisy) → × 0.7
- MACD × 1.0 (OK) → × 1.0
- BB × 0.85 → × 0.85
- Stoch × 0.75 → × 0.5
- EMA × 0.75 → × 1.5 (filtre tendance plus important)

Tester walk-forward, garder si meilleur.

**Effort** : ~1 jour

#### 3.3 Volume confirmation

Ajouter une condition `volume[-1] > 1.5 × moyenne(volume, 20)` pour
valider tout signal. Logique propre, isolée.

**Effort** : ~1 jour

#### 3.4 Pullback detection

Ne BUY qu'après une correction ≥ 2 ATR dans une tendance haussière
confirmée. Évite les FOMO entries.

**Effort** : ~2 jours

#### 3.5 Activer ensemble + MTF en LIVE

Vérifier que les filtres avancés (désactivés en backtest UI) sont
**bien activés** en production. Mesurer impact sur trading réel.

**Effort** : ~1 jour

#### 3.6 Tester sur historique long

Trouver source de données 2-3 ans (CryptoCompare, Kaiko...) pour
walk-forward étendu.

**Effort** : ~2 jours

### Critères de succès du palier

- Walk-forward Sharpe avg > 1.0
- Walk-forward PF avg > 1.5
- Walk-forward consistency > 60 %
- Le bot s'améliore mesurablement vs début (poids stratégies ont
  évolué dans le bon sens)

---

## Palier 4 — Sécurité production

### Objectif

Durcir la sécurité avant d'augmenter le capital.

### Travaux

#### 4.1 Migration vers Android KeyStore (pyjnius)

Au lieu de PBKDF2+XOR pour les clés API, utiliser le KeyStore
natif Android (hardware-backed sur les téléphones modernes).

**Effort** : ~3-5 jours (recherche + implémentation + tests)

#### 4.2 Backup chiffré cloud opt-in

Permettre à l'utilisateur de sauvegarder sa DB chiffrée vers Google
Drive ou Dropbox **avec sa propre clé**. Désactivé par défaut.

**Effort** : ~3 jours

#### 4.3 2FA sur actions critiques

Demander confirmation biométrique (empreinte) pour :
- Activer Bot Maître en réel
- Augmenter le budget > 100 USD
- Synchroniser solde Binance
- Emergency Stop

**Effort** : ~2 jours

### Critères de succès

- Clés API en KeyStore (pas dans la DB)
- Backup cloud disponible et testé
- 2FA opérationnelle

---

## Palier 5 — Croissance capital

### Objectif

Quand l'utilisateur est confiant et que les paliers 1-4 sont validés,
augmenter le capital progressivement.

### Étapes prudentes

| Étape | Capital | Conditions |
|---|---|---|
| 5.1 | 50 USD | 30 jours en 20$ avec ROI ≥ 0 % |
| 5.2 | 100 USD | 30 jours en 50$ avec ROI ≥ 0 % |
| 5.3 | 250 USD | 60 jours en 100$ avec ROI ≥ +5 % cumul |
| 5.4 | 500 USD | 60 jours en 250$ avec ROI ≥ +10 % cumul |
| 5.5 | 1000 USD | 90 jours en 500$ avec ROI ≥ +15 % cumul |
| 5.6 | > 1000 USD | À discuter |

### Activation progressive de fonctionnalités

À mesure que le capital grandit :

- **100 USD** : `max_positions=2` (diversification raisonnable)
- **250 USD** : `max_positions=3`
- **500 USD+** : Considérer multi-exchanges (Coinbase, Kraken)

### Anti-pattern à éviter

🔴 **JAMAIS d'augmentation de capital sans 30j de track record**
positif sur le palier précédent.

🔴 **JAMAIS de "all-in"** : garder toujours un buffer de 20 % du
capital hors bot (en USD libre sur Binance).

---

## Palier 6 — Niveau Entreprise validé

### Objectif

L'app a atteint et **maintient** le niveau de service défini dans
[09_NIVEAU_ENTREPRISE.md](09_NIVEAU_ENTREPRISE.md). C'est l'objectif
ultime du projet : être un **outil sur lequel l'utilisateur peut
compter 24/7 sans rien savoir des détails techniques**.

### Conditions de passage

Tous les critères E1-E20 ✅ pendant **3 mois consécutifs**.

### Travaux nécessaires (chronologie)

#### Mois 1-3 — Implémentation des fonctionnalités enterprise

| Mois | Action | Critère(s) débloqué(s) |
|---|---|---|
| 1 | Architecture Actif/Réserve + skim hebdo | E12, E13 |
| 1 | WalletManager module + tests pytest | – |
| 1 | Onboarding wizard 4 étapes | E6 |
| 2 | Rapports Telegram (quotidien + hebdo) | E9, E10 |
| 2 | Export PDF/CSV mensuel | E11 |
| 2 | Refus clé API avec WITHDRAW | E19 |
| 3 | Migration Android KeyStore | E7 |
| 3 | 2FA biométrique sur toggles critiques | E8 |
| 3 | Mode "Explication" sur tous les écrans | UX bonus |

#### Mois 4-6 — Mesure des SLA

| Mois | Action | Critère(s) débloqué(s) |
|---|---|---|
| 4 | Profiling mémoire continu | E3 |
| 4 | Mesure batterie réelle 30j | E4 |
| 4 | Mesure latence cycle | E5 |
| 5 | Test forcé recovery | E2 |
| 5 | Mesure DB sur 90j d'usage | E16 |
| 6 | Mesure uptime 30 jours glissants | E1 |

#### Mois 7-12 — Maintien et raffinement

À cette phase, l'app **doit** simplement **continuer à tourner** en
tenant tous ses SLA. Toute régression mesurée est un incident à
traiter en priorité.

L'utilisateur doit vivre une expérience qui **devient invisible** :
il ouvre l'app de temps en temps, regarde son ROI, et c'est tout.

### Critères de succès final

- ✅ 100 % des critères T1-T20 atteints
- ✅ 100 % des critères E1-E20 atteints sur 3 mois consécutifs
- ✅ Capital total > 1.5× capital initial (= bot a vraiment fait gagner
  de l'argent net après tous les frais)
- ✅ Témoignage utilisateur : "Je n'y pense plus, ça tourne tout seul"

### Si on n'y arrive pas en 12 mois

Honnêtement, le projet doit accepter qu'il **n'a pas atteint le
niveau entreprise** et soit :
- Continuer (palier 7+ improvisé) avec patience
- Reconnaître publiquement (dans README et docs/PROJECT_STATE) que le
  niveau cible n'est pas tenu, et ajuster la promesse

**Pas de mensonge** sur l'état d'atteinte des SLA.

---

## Tableau récapitulatif des critères de terminaison

### Critères MVP (T1-T20) — état actuel

| # | Critère | État aujourd'hui |
|:-:|---|:-:|
| T1 | Tests pytest 100 % | ✅ 311/311 |
| T2 | CI verte | ✅ |
| T3 | App desktop sans crash 1h | ✅ |
| T4 | APK Android sans crash 24h | 🔴 jamais testé |
| T5 | Persistance vérifiée runtime | 🔴 |
| T6 | Connexion Binance vérifiée | 🔴 |
| T7 | Backtest produit trades réalistes | ✅ |
| T8 | Walk-forward Sharpe avg ≥ **1.5** *(durci 0.5 → 1.5)* | 🔴 0.93 |
| T9 | Walk-forward PF avg ≥ **1.8** sur **tous les régimes** *(durci 1.2 → 1.8)* | ⚠️ 3.03 moyenne, à vérifier par régime |
| T10 | Walk-forward consistency ≥ **65 %** *(durci 50 → 65)* | 🔴 40 % |
| T8b | Beat HODL BTC sur 90j glissants | 🔴 jamais mesuré |
| T11 | Max Drawdown < 20 % | ✅ |
| T12 | 0 fuite de clé API | ✅ |
| T13 | Confirmation argent réel sur tous toggles | ✅ |
| T14 | Audit trail JSON complet | ✅ |
| T15 | Backup DB + restore validé | ✅ |
| T16 | Documentation à jour | ✅ |
| T17 | README clair | ✅ |
| T18 | Paper mode tourné > 1h sans incident | 🔴 |
| T19 | Notifications Telegram opérationnelles | 🔴 |
| T20 | Health check production | ✅ |

### Critères Niveau Entreprise (E1-E20) — état actuel

> Ces critères sont issus de [09_NIVEAU_ENTREPRISE.md](09_NIVEAU_ENTREPRISE.md).
> Ils définissent le passage de "MVP fonctionnel" à "outil de niveau
> entreprise réel". Engagement à 6-12 mois.

| # | Critère | État aujourd'hui |
|:-:|---|:-:|
| E1 | Uptime ≥ 99 % sur 30 jours glissants | 🔴 jamais mesuré |
| E2 | Recovery automatique < 60 sec après crash | ⚠️ code OK, jamais validé runtime |
| E3 | Empreinte mémoire ≤ 200 MB | 🔴 jamais profilé |
| E4 | Consommation batterie ≤ 3 % / 24h | 🔴 jamais mesuré |
| E5 | Cycle complet ≤ 30 sec | ⚠️ probablement OK, à mesurer |
| E6 | Onboarding < 5 min pour novice | 🔴 wizard pas encore créé |
| E7 | Clés API en KeyStore (pas DB) | 🔴 PBKDF2+XOR actuel |
| E8 | 2FA biométrique sur actions critiques | 🔴 |
| E9 | Rapport quotidien Telegram | 🔴 pas implémenté |
| E10 | Rapport hebdo Telegram | 🔴 |
| E11 | Rapport mensuel PDF/CSV exportable | 🔴 |
| E12 | Architecture Actif/Réserve fonctionnelle | 🔴 pas implémentée |
| E13 | Skim hebdomadaire automatique | 🔴 |
| E14 | Audit forensique queryable | ✅ (déjà via `audit.query_events`) |
| E15 | Circuit Breaker 4 niveaux validé runtime | ⚠️ code OK, jamais déclenché en réel |
| E16 | DB ≤ 50 MB après 90j usage | 🔴 jamais mesuré |
| E17 | APK ≤ 50 MB | ✅ ~35 MB actuel |
| E18 | Aucune fuite de secret en logs | ✅ |
| E19 | Refus si clé API a WITHDRAW | 🔴 pas vérifié |
| E20 | Backup DB chiffré + restore validé runtime | ⚠️ tests pytest OK, runtime user manquant |

### Critères Edge concurrentiel (I1-I12) — état actuel

> Ces critères sont issus de [10_INNOVATIONS_ET_EDGE.md](10_INNOVATIONS_ET_EDGE.md).
> Ils mesurent **l'avance technique** par rapport aux bots retail
> standards. Sans eux, Emeraude reste un "bot correct" et non
> "le meilleur des meilleurs".

| # | Critère | État aujourd'hui |
|:-:|---|:-:|
| I1 | ECE de calibration < 5 % sur 100 trades | 🔴 module pas créé |
| I2 | Écart backtest adversarial vs réel ≤ 15 % | ⚠️ backtest standard OK, mode adversarial à coder |
| I3 | Drift détecté ≤ 72h sur injection synthétique | 🔴 module pas créé |
| I4 | Champion robuste à ±20 % perturbation paramètres | ⚠️ walk-forward OK, robustness check à ajouter |
| I5 | Max DD réel ≤ 1.2 × CVaR_99 | 🔴 VaR Gaussienne actuelle, tail risk à coder |
| I6 | Microstructure apporte ≥ +0.1 Sharpe | 🔴 module pas créé |
| I7 | Régime stress corrélation détecté ≤ 1 cycle | ⚠️ corrélation OK, seuil stress à ajouter |
| I8 | Meta-gate réduit trades ≥ 30 % sans baisse PnL | 🔴 module pas créé |
| I9 | Slippage moyen ≤ 0.05 % par trade | 🔴 exécution market pure actuelle |
| I10 | 100 % états critiques restaurés après kill -9 | ⚠️ checkpoint OK, learning_history à étendre |
| I11 | 0 % updates de poids sur < 30 trades (Hoeffding) | 🔴 garde-fou statistique à ajouter |
| I12 | Dashboard performance lisible ≤ 5 s | 🔴 écran performance à créer |

### Critères Intégrité données (D1-D6) — état actuel

> Issus de [11_INTEGRITE_DONNEES.md](11_INTEGRITE_DONNEES.md). Sans
> intégrité, **toutes** les autres métriques (Sharpe, ECE, walk-forward)
> sont suspectes.

| # | Critère | État aujourd'hui |
|:-:|---|:-:|
| D1 | Test no-lookahead vert sur 100 % modules signal | 🔴 test pas créé |
| D2 | Backtest produit header avec snapshot d'univers | 🔴 |
| D3 | ≥ 1 événement `bar_quality_warning` / mois en audit | 🔴 module pas créé |
| D4 | 0 cycle sans flag `data_quality` rempli | 🔴 |
| D5 | Test no-naive-datetime vert | 🔴 test pas créé |
| D6 | 2 runs identiques → hash sortie identique | 🔴 snapshot pas codé |

### Critères Cold-start (CS1-CS4) — état actuel

> Issus de [04_STRATEGIES_TRADING.md](04_STRATEGIES_TRADING.md) §
> Cold-start protocol. Garantit la prudence bayésienne sur les 30
> premiers jours en réel.

| # | Critère | État aujourd'hui |
|:-:|---|:-:|
| CS1 | Aucun trade > cap de phase courante | 🔴 phases pas implémentées |
| CS2 | Promotion uniquement si seuil + condition validation | 🔴 |
| CS3 | Rétrogradation effective ≤ 1 cycle | 🔴 |
| CS4 | Bandeau phase visible en permanence | 🔴 UI pas créée |

### Critères Graceful degradation (G1-G4) — état actuel

> Issus de [09_NIVEAU_ENTREPRISE.md](09_NIVEAU_ENTREPRISE.md) §
> Graceful degradation. Comportement défini en zone grise (Binance
> half-broken, Telegram down, etc.).

| # | Critère | État aujourd'hui |
|:-:|---|:-:|
| G1 | Matrice testable via simulation mock | 🔴 tests pas créés |
| G2 | Transition d'état dégradé ≤ 1 cycle | 🔴 logique pas codée |
| G3 | 0 entrée nouvelle en état FREEZE/EXITS_ONLY | 🔴 |
| G4 | Retour à NORMAL automatique quand deps OK | 🔴 |

### Critères Human override (H1-H4) — état actuel

> Issus de [02_EXPERIENCE_UTILISATEUR.md](02_EXPERIENCE_UTILISATEUR.md) §
> Human override. Garantit l'absence de conflit auto/manuel.

| # | Critère | État aujourd'hui |
|:-:|---|:-:|
| H1 | Overrides loggés `audit_log` type `manual_*` | ⚠️ partiellement (fermeture manuelle existe) |
| H2 | Réconciliation DB ↔ Binance à chaque cycle | 🔴 pas implémentée |
| H3 | 0 conflit auto/manuel non détecté / 30j | 🔴 jamais mesuré |
| H4 | Stop d'urgence ferme 100 % positions ≤ 30 s | 🔴 bouton pas créé |

### Critères Champion lifecycle (CL1-CL4) — état actuel

> Issus de [10_INNOVATIONS_ET_EDGE.md](10_INNOVATIONS_ET_EDGE.md) § 7.
> Empêche un champion obsolète de continuer à trader en aveugle.

| # | Critère | État aujourd'hui |
|:-:|---|:-:|
| CL1 | Re-validation 1×/mois minimum | 🔴 module pas créé |
| CL2 | Transition d'état ≤ 1 cycle | 🔴 |
| CL3 | Aucun champion EXPIRÉ en sizing nominal | 🔴 |
| CL4 | `champion_history` liste tous les champions passés | 🔴 table pas créée |

### Score consolidé

**MVP** (T1-T20+T8b) : 12/21 ✅ *(durcissement T8/T9/T10 → 3 critères qui repassent en 🔴)*
**Niveau Entreprise** (E1-E20) : 1/20 ✅ + 4 ⚠️ (palier 6)
**Edge concurrentiel** (I1-I12) : 0/12 ✅ + 4 ⚠️ (palier 7)
**Intégrité données** (D1-D6) : 0/6 (palier 7 — bloquant)
**Cold-start** (CS1-CS4) : 0/4 (palier 1 — bloquant trading réel)
**Champion lifecycle** (CL1-CL4) : 0/4 (palier 7)
**Graceful degradation** (G1-G4) : 0/4 (palier 6)
**Human override** (H1-H4) : 0/4 + 1 ⚠️ (palier 1-2)

**Score global** : **13/75 ✅** des critères "le meilleur des meilleurs"

> **Note d'honnêteté** : le score baisse encore (14/66 → 13/75) parce
> que (a) on durcit 3 cibles walk-forward sur la barre institutionnelle
> au lieu de la barre molle, et (b) on formalise 8 nouveaux critères
> (G1-G4 + H1-H4). C'est la **rigueur qui monte**, pas la qualité qui
> baisse. Préférer 13/75 honnête à 14/52 fantaisiste.

### Conditions de passage par palier

- **→ Palier 1 (trading réel 20 USD)** : T4, T5, T6, T18 ✅ minimum
- **→ Palier 2 (stabilisation 30j)** : tous les T1-T20 ✅
- **→ Palier 3 (calibration alpha)** : T10 ✅ + ajout E12, E13 ✅
- **→ Palier 4 (sécurité production)** : E7, E8, E20 ✅
- **→ Palier 5 (croissance capital)** : E1-E5 (SLA opérationnels) ✅
- **→ Palier 6 (Niveau Entreprise validé)** : tous les T1-T20 et E1-E20 ✅
- **→ Palier 7 (Edge concurrentiel)** : tous les I1-I12 + D1-D6 + CL1-CL4 ✅
  - Phase A (intégrité données) : D1-D6 ✅ — **prérequis tous les autres**
  - Phase B (fondations stat) : I1, I5, I11, I12 ✅
  - Phase C (régime) : I3, I7, I8 ✅
  - Phase D (exécution) : I2, I6, I9 ✅
  - Phase E (mémoire + lifecycle) : I4, I10, CL1-CL4 ✅
- **→ Trading réel sécurisé** (préalable au palier 1) : tous les CS1-CS4 ✅

---

*v1.3 — 2026-04-25 — durcissement T8/T9/T10 (cibles institutionnelles) + ajout T8b, G1-G4 (degradation), H1-H4 (override). Score 13/75.*
