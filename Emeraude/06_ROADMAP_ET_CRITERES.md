# 06 — Roadmap et Critères de Terminaison

> Le projet avance par **paliers de validation**. Chaque palier a des
> conditions de passage **mesurables**. On ne passe pas au palier
> suivant sans avoir validé le précédent.

---

## Schéma global

```
   ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
   │ Palier 0│ →  │ Palier 1│ →  │ Palier 2│ →  │ Palier 3│ →  │ Palier 4│
   │ État    │    │ Trading │    │ Stabili-│    │ Calibra-│    │ Sécurité│
   │ courant │    │ réel    │    │ sation  │    │ tion    │    │ produc- │
   │         │    │ 20 USD  │    │ 30 jours│    │ alpha   │    │ tion    │
   └─────────┘    └─────────┘    └─────────┘    └─────────┘    └─────────┘
                                                                     │
                                                                     ▼
                                                              ┌─────────┐
                                                              │ Palier 5│
                                                              │ Crois-  │
                                                              │ sance   │
                                                              │ capital │
                                                              └─────────┘
```

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

## Tableau récapitulatif des 20 critères de terminaison

| # | Critère | État aujourd'hui |
|:-:|---|:-:|
| 1 | Tests pytest 100 % | ✅ 311/311 |
| 2 | CI verte | ✅ |
| 3 | App desktop sans crash 1h | ✅ |
| 4 | APK Android sans crash 24h | 🔴 jamais testé |
| 5 | Persistance vérifiée runtime | 🔴 (code OK, capture user manquante) |
| 6 | Connexion Binance vérifiée | 🔴 (code OK, capture user manquante) |
| 7 | Backtest produit trades réalistes | ✅ |
| 8 | Walk-forward Sharpe avg ≥ 0.5 | ✅ +0.93 |
| 9 | Walk-forward PF avg ≥ 1.2 | ✅ 3.03 |
| 10 | Walk-forward consistency ≥ 50 % | 🔴 40 % |
| 11 | Max Drawdown < 20 % | ✅ |
| 12 | 0 fuite de clé API | ✅ |
| 13 | Confirmation argent réel sur tous toggles | ✅ |
| 14 | Audit trail JSON complet | ✅ |
| 15 | Backup DB + restore validé | ✅ |
| 16 | Documentation à jour | ✅ |
| 17 | README clair | ✅ |
| 18 | Paper mode tourné > 1h sans incident | 🔴 |
| 19 | Notifications Telegram opérationnelles | 🔴 (user pas accès) |
| 20 | Health check production | ✅ |

**Score actuel** : 13/20 ✅, 0 ⚠️, 7 🔴

**Pour passer en argent réel (palier 1)** : critères #4, #5, #6, #18
doivent passer ✅ minimum. #19 nullable car notif optionnelle.

**Pour considérer "meilleur des meilleurs"** : tous ces critères + le
walk-forward consistency #10 doit passer (refonte palier 3).

---

*v1.0 — 2026-04-25*
