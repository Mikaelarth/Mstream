# 09 — Niveau Entreprise

> Ce document définit ce qui sépare un **MVP fonctionnel** d'un
> **outil de niveau entreprise réel**. C'est l'engagement que le
> projet prend pour passer de "ça marche" à "on peut compter dessus
> 24/7".

---

## Définition opérationnelle de "niveau entreprise"

Un outil **de niveau entreprise** se reconnaît à 6 attributs :

1. **Disponibilité** : tourne 24/7 sans intervention
2. **Robustesse** : survit aux incidents (crash, réseau, mises à jour OS)
3. **Observabilité** : ce qui se passe est mesurable et auditeur en
   permanence
4. **Sécurité** : les actifs et données sont protégés au niveau hardware
5. **Simplicité utilisateur** : zéro friction, zéro savoir technique requis
6. **Engagement de service** (SLA) : un niveau de qualité chiffré et tenu

Ces 6 attributs sont **mesurables**, **objectifs** et **vérifiables**.

---

## SLA self-imposed (engagements chiffrés)

> Le projet s'engage envers son utilisateur sur les niveaux de service
> ci-dessous. Si l'un est manqué, c'est un incident à corriger en
> priorité.

### Disponibilité (uptime)

| Métrique | Cible | Comment mesurer |
|---|---|---|
| Uptime app Android | **≥ 99 %** sur 30 jours glissants | Logs de cycle (un cycle attendu toutes les 60 min) |
| Uptime cycle de trading | **≥ 99 %** des cycles complétés sans erreur | Audit `cycle_completed` |
| Recovery automatique après crash | **≤ 60 secondes** | Auto-recovery via checkpoint |

### Latence

| Métrique | Cible | Comment mesurer |
|---|---|---|
| Durée d'un cycle complet (fetch + analyse + décision) | **≤ 30 secondes** | Logs cycle |
| Affichage écran Dashboard au lancement | **≤ 2 secondes** | Profiling Kivy |
| Temps de réponse à une action (tap → feedback) | **≤ 100 ms** pour locale, ≤ 1 s pour réseau | Capture user / observation |

### Ressources

| Métrique | Cible | Comment mesurer |
|---|---|---|
| Empreinte mémoire | **≤ 200 MB** RAM en usage normal | Android Studio Profiler |
| Consommation batterie | **≤ 3 %** par 24h en arrière-plan | Android Battery Settings |
| Taille DB après 90 jours d'usage | **≤ 50 MB** | `ls -lh mstream_trader.db` |
| Taille APK | **≤ 50 MB** | Buildozer output |

### Performance financière (au-delà du technique)

| Métrique | Cible (palier 2 — 30j en réel) | Comment mesurer |
|---|---|---|
| ROI net après frais sur 30j | **≥ 0 %** (ne perd pas) | Audit + Binance |
| Drawdown max | **< 20 %** à tout moment | Circuit breaker + audit |
| Trades exécutés | **≥ 5** sur 30j | Audit |

---

## Robustesse : 5 modes de défaillance gérés

### Mode 1 — Crash de l'app

**Détection** : checkpoint manquant (`auto_trader._cycle_count` non
incrémenté pendant > 90 min).

**Réaction** :
- Auto-recovery au prochain démarrage via `core/checkpoint.auto_recover_on_startup()`
- Restauration du dernier état volatile (Circuit Breaker, régime, peak
  capital)
- Notification Telegram à l'utilisateur ("App redémarrée après crash")

**SLA** : recovery < 60 secondes après lancement.

### Mode 2 — Perte de réseau

**Détection** : 3 cycles consécutifs avec `last_fetch_error` non-vide.

**Réaction** :
- Pas de nouveaux trades (filtre fail-safe)
- Continuation du monitoring des positions ouvertes (SL local possible)
- Notification user si > 30 min sans réseau

**SLA** : reprise automatique dès que réseau disponible.

### Mode 3 — Erreur Binance API

**Détection** : codes -1003 (rate limit), -1001 (disconnected),
HTTP 5xx.

**Réaction** :
- Retry exponentiel via `core.retry.retry_binance` (3 tentatives,
  backoff 0.5s → 2s → 8s)
- Si échec persistant : Circuit Breaker → état FROZEN après 5 erreurs
  consécutives
- Notification user + audit complet

**SLA** : un échec API isolé n'impacte pas les positions ouvertes.

### Mode 4 — Mise à jour Android OS

**Risque** : l'OS tue l'app en arrière-plan, modifie les permissions.

**Réaction** :
- Persistance via `core/paths.py` qui survit aux mises à jour
- Backup DB chiffré (palier 4 du roadmap)
- Re-authentification biométrique demandée au lancement post-update

**SLA** : aucune perte de données suite à mise à jour OS.

### Mode 5 — Bug logique du bot (drawdown anormal)

**Détection** : Circuit Breaker 4 niveaux dans `core/circuit_breaker.py`
- 5 SL consécutifs → TRIGGERED
- > 10 % DD en 4h → TRIGGERED
- > 20 % DD total (peak) → TRIGGERED
- 5 erreurs API → FROZEN

**Réaction** :
- Bot s'arrête de prendre des positions
- Positions existantes restent ouvertes (pas de panic-close)
- Notification user critique
- Auto-recovery TRIGGERED → WARNING après 12h, WARNING → HEALTHY après
  2h

**SLA** : aucune perte > 20 % du capital sans Circuit Breaker activé.

---

## Graceful degradation : matrice de dépendances dégradées

Les 5 modes de défaillance ci-dessus traitent les **pannes franches**.
Mais la majorité des incidents réels sont des **dégradations
partielles** : Binance API qui répond mais lentement, prix obsolètes,
read OK mais write KO. Sans matrice explicite, le bot prend des
décisions incohérentes en zone grise.

### Matrice de décision par dépendance

| Dépendance | État dégradé | Décision Emeraude | Justification |
|---|---|---|---|
| **Binance public klines** | Latence > 10 s OU < 50 % bars attendus | Skip cycle entrée, **conserver gestion exits** (SL/TP existants) | Pas de nouveau pari sur donnée incertaine ; les SL serveur tournent côté Binance |
| **Binance trading API** | Read OK / Write KO | **FREEZE entrées** + tentative annulation des SL pendants ; alerte utilisateur | Empêcher d'ouvrir une position qu'on ne pourrait pas fermer |
| **Binance trading API** | Write OK / Read KO | **FREEZE entrées** + position courante en mode "trust SL serveur" | On a placé les SL côté Binance, ils protègent même sans read |
| **Binance API totalement down** | Aucune réponse > 60 s | Circuit Breaker → FROZEN, alerte critique utilisateur | Mode dégradation maximale, intervention humaine nécessaire |
| **CoinGecko** (prix secondaire) | Indisponible | Continuer avec données Binance seules | Source non-critique, fallback OK |
| **Telegram** | Indisponible | Continuer trading, **buffer notifications** en DB, retry exponentiel | Notif est observabilité, pas décision |
| **Connexion réseau** | Coupée | Pause cycle, retry chaque 60 s, état "OFFLINE" affiché | Conserve état local, reprend dès retour |
| **Disque saturé** (DB lock) | Écriture impossible | **STOP toutes opérations** + alerte critique | Sans audit trail, on ne trade pas |
| **Mémoire saturée** | OOM imminent | Drop caches, refuse nouvelles entrées, alerte | Préserver intégrité plutôt que crash |
| **Horloge système** désynchronisée > 5 s | Refus signature Binance | **STOP** + alerte « régler l'heure du téléphone » | Les ordres Binance échouent, signature timestamp |

### Principe de hiérarchie

Quand plusieurs dégradations co-existent, on applique la règle la
**plus restrictive** :

```
NORMAL  →  ENTRÉES FREEZE  →  EXITS ONLY  →  FROZEN  →  STOP TOTAL
   ↑                                                          ↓
   └──── retour automatique si toutes deps redeviennent OK ───┘
```

### Audit obligatoire

Chaque transition d'état dégradé est un événement
`degradation_state_change` dans `audit_log` :

```json
{
  "from_state": "NORMAL",
  "to_state": "EXITS_ONLY",
  "trigger": "binance_write_api_5xx_repeated",
  "duration_seconds": 0,
  "user_notified": true
}
```

→ Permet le post-mortem : "à quel moment Emeraude a basculé en
EXITS_ONLY, et combien de temps il y est resté ?"

### Critères mesurables (G1-G4)

| # | Critère | Validation |
|:-:|---|---|
| G1 | Chaque ligne de la matrice testable via simulation (mock dépendance) | suite pytest |
| G2 | Transition d'état dégradé ≤ 1 cycle | audit trail |
| G3 | Aucune entrée nouvelle en état FREEZE/EXITS_ONLY | audit query |
| G4 | Retour à NORMAL automatique quand deps OK | test E2E |

---

## Observabilité : ce qui doit être mesuré et visible

### Métriques exposées dans l'écran "État système" (à créer)

Un nouvel écran (ou panneau dans Config) doit afficher :

```
┌───────────────────────────────────────────────────┐
│  ÉTAT SYSTÈME                              [Refresh] │
├───────────────────────────────────────────────────┤
│  ✅ Bot              : ACTIF (cycle #1247)         │
│  ✅ Connexion Binance : OK (latence 230 ms)         │
│  ✅ Circuit Breaker  : HEALTHY                      │
│  ✅ Régime marché    : BULL (BTC +3.2% vs EMA200)   │
│                                                   │
│  📊 Uptime 7 jours   : 99.4 %                      │
│  ⚡ Dernier cycle    : 18 sec                      │
│  💾 DB              : 12.3 MB / 50 MB              │
│  🔋 Batterie 24h    : 1.8 %                        │
│                                                   │
│  📈 Performance 30j                                │
│     Trades        : 7 (4W / 3L = 57 % win)         │
│     ROI net       : +2.3 %                         │
│     Drawdown max  : 4.1 %                          │
│                                                   │
│  💼 Portefeuilles                                  │
│     Actif         : $18.50                         │
│     Réserve       : $5.80                          │
│     Total         : $24.30 (+21.5 %)               │
│                                                   │
│  🚨 Alertes actives : 0                            │
└───────────────────────────────────────────────────┘
```

### Audit forensique

Tout est traçable via `core.audit.query_events()` :

- Par `event_type` (15 types)
- Par `coin_id`
- Par `cycle_id` (groupement)
- Par `severity` (info, warning, critical)
- Par plage de dates

Rétention : 30 jours (purge auto).

### Reporting périodique automatique (à implémenter)

#### Rapport quotidien (Telegram)

Envoyé à 22:00 UTC chaque jour si Telegram configuré :

```
📊 Emeraude — Rapport quotidien

Trades exécutés aujourd'hui : 1
P&L jour : +0.42 USDT (+2.1 %)
Capital total : $24.72
Régime marché : BULL
Position(s) ouverte(s) : 1 (BTC, +1.2 %)

État : ✅ Tout va bien
```

#### Rapport hebdomadaire (Telegram + écran dédié)

Chaque dimanche à 23:00 UTC, après le skim :

```
📈 Emeraude — Rapport hebdomadaire

Période : 22 → 28 avril 2026
Trades : 6 (4W / 2L = 67 % win rate)
P&L semaine : +1.83 USDT (+9.2 %)

💰 Skim de la semaine : 0.92 USDT → Réserve
   (Palier P2 — 50 % des gains)

🤖 Apprentissage du bot
   Trend Follower    : +0.4 R/trade (5 trades)
   Mean Reversion    : -0.1 R/trade (1 trade)
   Breakout Hunter   : N/A (0 trade)

Total cumulé : Capital $24.30, Réserve $5.80
```

#### Rapport mensuel (PDF/CSV exporté)

À la fin de chaque mois calendaire, l'app génère un PDF/CSV
téléchargeable contenant :
- Tous les trades (entrée, sortie, raison, P&L)
- Performance jour par jour
- Évolution Actif / Réserve
- Performance par stratégie
- Régimes traversés

---

## Sécurité niveau entreprise

### Hiérarchie de protection des secrets

| Niveau | Mécanisme | État actuel |
|---|---|---|
| 1 — Obfuscation | PBKDF2 + XOR + sel séparé | ✅ |
| 2 — Storage privé Android | `app_storage_path()` | ✅ |
| 3 — Chiffrement hardware-backed | Android KeyStore | 🔴 Palier 4 |
| 4 — Authentification biométrique | Empreinte / Face ID via Android API | 🔴 Palier 4 |
| 5 — 2FA pour actions critiques | Confirmation biométrique sur toggles | 🔴 Palier 4 |

### Politique des permissions Binance

L'utilisateur doit créer une clé API Binance avec **uniquement** :
- ✅ READ (lire le solde)
- ✅ TRADE (passer des ordres spot)
- ❌ **WITHDRAW** : NE JAMAIS activer

Cette politique est **enforcée** dans l'app : si la clé a la
permission WITHDRAW, l'app affiche un avertissement et refuse de
trader tant que l'utilisateur n'a pas régénéré une clé sans WITHDRAW.

### Audit de sécurité périodique

Tous les 30 jours, un audit auto :
- Vérifie qu'aucun TODO/FIXME critique n'est laissé
- Vérifie qu'aucun secret n'est en clair dans la DB
- Vérifie que les sels et clés dérivées sont à jour
- Vérifie que la dernière sauvegarde DB est < 7 jours

---

## Simplicité utilisateur : "zéro friction" mesuré

### Le test "5 minutes"

Un utilisateur **novice** (n'a jamais utilisé l'app) doit pouvoir,
en moins de 5 minutes, faire :

1. Installer l'APK
2. Connecter ses clés API Binance
3. Définir son budget (20 USD)
4. Activer le bot

**Sans avoir lu de documentation**.

### Onboarding wizard (à créer)

Un wizard en 4 étapes au premier lancement :

```
Étape 1/4 : Bienvenue
  "Emeraude va trader pour toi 24/7. Avant de commencer, on a
   besoin de 3 informations."
  [Commencer →]

Étape 2/4 : Connexion Binance
  "Colle ta clé API et ton secret API. Création gratuite sur
   Binance.com → API Management."
  [Champ clé API]
  [Champ secret API]
  [⚠ IMPORTANT : ne pas activer WITHDRAW]
  [Tester la connexion]

Étape 3/4 : Budget
  "Combien veux-tu allouer au bot ? (en USDT)"
  [Champ budget : 20.00]
  "Le bot va répartir : Actif (capital de travail) + Réserve
   (sécurise tes gains progressivement)"

Étape 4/4 : Confirmation
  "Tout est prêt. Le bot va commencer ses analyses dans 60
   secondes. Tu peux le surveiller depuis l'écran principal."
  [Activer le bot →]
```

### "Zéro savoir technique requis"

Un utilisateur n'a **JAMAIS** à comprendre :
- RSI, MACD, Bollinger Bands (caché derrière "le bot évalue le marché")
- Walk-forward, Sharpe ratio (caché derrière "le bot s'améliore")
- Régime, ensemble, MTF (caché derrière "le bot adapte sa stratégie")
- Kelly, Vol-targeting (caché derrière "le bot dimensionne ses positions")

Mais il **PEUT** voir ces infos s'il veut, via un mode "détails" opt-in
sur chaque écran (cf. doc 02 — mode explication).

---

## Critères de validation niveau entreprise

L'application est considérée **niveau entreprise** quand TOUS les
critères suivants sont ✅ :

| # | Critère | Mesure |
|:-:|---|---|
| E1 | Uptime ≥ 99 % sur 30 jours glissants | Logs |
| E2 | Recovery automatique < 60 sec après crash | Test forcé |
| E3 | Empreinte mémoire ≤ 200 MB | Android Profiler |
| E4 | Consommation batterie ≤ 3 % / 24h en arrière-plan | Android Settings |
| E5 | Cycle complet ≤ 30 sec | Logs |
| E6 | Onboarding < 5 min pour novice | Test utilisateur |
| E7 | Clés API en KeyStore (pas DB) | Code review |
| E8 | 2FA biométrique sur actions critiques | Test fonctionnel |
| E9 | Rapport quotidien Telegram opérationnel | Test envoi |
| E10 | Rapport hebdo Telegram opérationnel | Idem |
| E11 | Rapport mensuel PDF/CSV exportable | Test export |
| E12 | Architecture Actif/Réserve fonctionnelle | Test transferts |
| E13 | Skim hebdomadaire automatique fonctionnel | Test cycle dimanche |
| E14 | Audit forensique queryable | Test query |
| E15 | Circuit Breaker 4 niveaux validé runtime | Test forcé |
| E16 | DB ≤ 50 MB après 90j usage | Test long terme |
| E17 | APK ≤ 50 MB | Buildozer |
| E18 | Aucune fuite de secret en logs | Audit logs |
| E19 | Refus si clé API a WITHDRAW | Test fonctionnel |
| E20 | Backup DB chiffré + restore validé | Test runtime |

**État aujourd'hui** : 0/20 mesurés (le projet n'a jamais tourné en
prod 30 jours). Les prérequis techniques sont là mais le **niveau
entreprise** se gagne par **mesure réelle**, pas par code.

---

## Engagement long-terme

Le passage au niveau entreprise est un **objectif à 6-12 mois**, pas
immédiat. Le chemin :

1. **Mois 1-2** : Lancer le bot en réel sur 20 USD, atteindre les
   critères de palier 2 (30j sans crash, ROI ≥ 0)
2. **Mois 3-4** : Implémenter les rapports automatiques (Telegram
   + PDF mensuel)
3. **Mois 5-6** : Migration KeyStore + biométrie (palier 4 du roadmap)
4. **Mois 7-12** : Mesurer les SLA, ajuster, atteindre le seuil
   entreprise validé

À 12 mois, l'app doit avoir réussi **20/20 critères E1-E20** pour être
qualifiée "niveau entreprise réel".

---

*v1.0 — 2026-04-25*
