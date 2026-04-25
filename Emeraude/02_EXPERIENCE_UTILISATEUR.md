# 02 — Expérience Utilisateur (Pilier #1)

> **L'UX est non-négociable.** Si une fonctionnalité techniquement
> brillante demande à l'utilisateur de réfléchir pour l'utiliser, elle
> est un échec UX, peu importe sa qualité algorithmique.

---

## Principes fondamentaux (les 7 commandements UX)

### 1. **Visibilité immédiate des états critiques**

À l'ouverture de l'app, l'utilisateur doit savoir **en moins de
3 secondes** :
- Le bot est-il actif ? ✅ ou ❌
- A-t-il des positions ouvertes ? Combien ? P&L net ?
- Est-il en mode paper ou réel ?
- La connexion Binance fonctionne-t-elle ?
- Quelque chose d'urgent ? (drawdown, circuit breaker, alerte)

**Implémentation** : barre d'état **persistante en haut** de chaque
écran avec ces 5 indicateurs. Pas de scroll requis.

### 2. **Feedback immédiat et précis pour chaque action**

Quand l'utilisateur clique :
- **Confirmation visuelle instantanée** (< 100 ms) que le clic est
  enregistré (animation, changement de couleur).
- **Feedback de résultat** (< 1 s pour action locale, toast pour
  action longue) : succès / échec avec **raison précise**.
- **Pas de "Erreur"** générique. Toujours dire quoi spécifiquement.

Mauvais : "Connexion échouée"
Bon : "Clés Binance rejetées (-2014). Vérifie qu'elles sont actives
       sur Binance et autorisent le trading."

### 3. **Aucune action critique sans confirmation explicite**

Pour toute action qui peut **perdre du capital** ou **toucher de
l'argent réel** :
- Double-tap obligatoire avec délai 5 secondes
- Message d'avertissement clair avec **le montant en jeu**
- Couleur rouge ou orange selon gravité

Exemples : activation Bot Maître en réel, Emergency Stop, suppression
de toutes les clés API.

### 4. **Aucune fonctionnalité fantôme**

Si un bouton est visible, il **fait quelque chose**. Pas de "Coming soon",
pas de placeholder, pas de switch déconnecté du code (cf. ancien
`auto_trade` switch supprimé en 2026-04-25).

### 5. **Cohérence absolue UI ↔ réalité**

Le texte affiché à l'utilisateur **doit refléter** l'état réel du code.
Pas de "5 minutes" affiché alors que le cycle est 60 minutes. Pas de
"Niveau hedge fund" alors que Sharpe est négatif.

**Test** : un développeur externe regarde l'UI et le code, est-il
trompé ? Si oui, c'est un bug.

### 6. **Lisibilité mobile-first sur Android**

- **Tailles de police minimum** :
  - Texte courant : 13 dp
  - Labels secondaires : 11 dp
  - Boutons : 14 dp gras
  - Headers : 18 dp gras
- **Cibles tactiles minimum** : 44 dp × 44 dp (Apple HIG / Material)
- **Contraste** : ratio AA minimum (4.5:1) sur thème sombre
- **Pas d'emoji** dans les labels critiques (boutons, états) — Roboto
  Android ne les rend pas. Réserver les emojis aux titres décoratifs
  (ou sur Windows desktop uniquement).

### 7. **Utilisable d'une main**

L'utilisateur doit pouvoir tout faire avec son pouce, en marchant.
- Boutons importants en bas de l'écran (zone pouce)
- Pas de glisser-déposer fin
- Tap simple suffit (jamais de long-press requis)

---

## Cartographie des 5 écrans avec leur mission UX

### 📊 DASHBOARD — "Voir d'un coup d'œil"

**Mission UX** : afficher en **3 secondes** l'état de mon argent et
des opportunités du moment.

**À voir d'un coup d'œil** :
- Solde USDT (réel ou paper selon mode)
- Valeur des positions ouvertes
- P&L total net (jour, semaine, total)
- Top 1 opportunité du moment
- Statut de connexion (Binance OK ou non)
- 8 cryptos avec prix + variation 24h + signal

**À ne PAS voir** : détails secondaires, listes longues, formulaires.

**Critère succès** : un utilisateur novice comprend l'état de son
argent en moins de 3 secondes.

### ⚡ SIGNAUX — "Comprendre les opportunités"

**Mission UX** : montrer pourquoi le bot pense qu'un coin est
intéressant ou non, **avec arguments lisibles**.

**Pour chaque coin** :
- Niveau de signal (ACHAT / ACHAT FORT / HOLD / VENTE)
- Score chiffré + niveau de confiance
- Ratio R/R proposé
- **3 raisons concrètes** ("RSI 28 — survente", "MACD croise au-dessus
  signal", etc.)
- Bouton "ACHETER" qui ouvre un dialog d'exécution

**Filtres** : Tous / Achat / Vente — top de l'écran.

**Critère succès** : un utilisateur peut justifier toute décision du
bot en lisant les raisons listées.

### 💼 PORTFOLIO — "Suivre mon argent"

**Mission UX** : afficher **clairement** où est mon argent et combien
j'ai gagné/perdu après frais.

**Sections** :
1. **Vue d'ensemble** : valeur totale, solde libre, P&L jour/total
2. **Bot Maître** : capital alloué, ROI réel après frais, positions
   ouvertes
3. **Évolution** : graphique simple (capital × temps)
4. **Positions ouvertes** : liste avec entry, current, P&L %
5. **Historique trades** : derniers 30 trades fermés
6. **Journal du bot** : décisions clés (entrée, sortie, skip avec
   raison)

**Critère succès** : l'utilisateur peut répondre à "combien j'ai
gagné cette semaine ?" en moins de 5 secondes.

### 🤖 IA / Apprentissage — "Voir le bot s'améliorer"

**NOUVEAU ÉCRAN À CRÉER**. Voir
[03_AGENT_INTELLIGENT_EVOLUTIF.md](03_AGENT_INTELLIGENT_EVOLUTIF.md).

**Mission UX** : montrer à l'utilisateur que le bot **apprend** et
**évolue**.

**À voir** :
- Performance de chaque stratégie (trend, reversion, breakout) :
  win rate, R-multiple moyen, nombre de trades
- Régime de marché actuel détecté
- Poids actuels des stratégies (vs poids initiaux)
- Évolution dans le temps (graphique)
- Top trades gagnants / perdants avec leçons apprises

**Critère succès** : l'utilisateur **voit** que le bot évolue
mesurablement.

### ⚙ CONFIG — "Tout paramétrer en sécurité"

**Mission UX** : permettre toutes les configurations critiques avec
**zéro risque** d'action accidentelle.

**Sections** : Connexion Binance, Capital, Risque, Bot Maître,
Portefeuilles legacy, Paper Trading, Telegram, Emergency Stop, Backtest.

**Garde-fous obligatoires** :
- Clés API jamais affichées en clair (déjà en place)
- Toggles d'argent réel exigent confirmation double-tap (déjà en place)
- Bornes max sur les budgets (déjà en place)
- Validation format des inputs (déjà en place)

**Critère succès** : impossible d'activer le trading réel par accident.

### 📈 BACKTEST — "Valider avant le réel"

**Mission UX** : permettre de tester la stratégie sur historique en
quelques tap, avec un rapport lisible.

**Workflow** :
1. Choisir nombre de jours (7-365)
2. Choisir capital initial
3. Choisir coins (présélection 4 majeurs par défaut)
4. Tap "Lancer" → 10-30 secondes d'attente avec spinner
5. Rapport lisible : ROI, Sharpe, Max DD, win rate, **diagnostic
   pourquoi 0 trades** si applicable

**Critère succès** : l'utilisateur comprend si la stratégie est
viable sur cet historique en lisant le rapport.

---

## Charte visuelle

### Palette de couleurs

| Usage | Couleur | Hex / RGBA |
|---|---|---|
| Fond principal | Anthracite | `#11121A` (0.07, 0.07, 0.10) |
| Cartes / panneaux | Gris foncé | `#1F2030` (0.12, 0.12, 0.18) |
| Texte principal | Blanc | `#FFFFFF` |
| Texte secondaire | Gris | `#999999` (0.6, 0.6, 0.6) |
| Succès / gain | Vert vif | `#00D966` (0.0, 0.85, 0.4) |
| Erreur / perte | Rouge vif | `#E63333` (0.9, 0.2, 0.2) |
| Avertissement | Orange | `#E69900` (0.9, 0.6, 0.0) |
| Info / lien | Bleu clair | `#4D99FF` (0.3, 0.6, 1.0) |
| Bot Maître (vert spécial) | Vert émeraude | `#00E673` (0.0, 0.9, 0.45) |

### Typographie

- **Police** : Roboto par défaut Kivy (Roboto Regular + Bold)
- **Sur Windows** : Segoe UI Emoji peut être enregistrée comme
  Roboto pour rendre les emojis (déjà fait dans `main.py`)
- **Sur Android** : Roboto bundlée par Kivy. Les emojis ne rendent
  pas → ne JAMAIS dépendre d'eux pour des éléments fonctionnels

---

## Tests UX obligatoires avant chaque livraison

À chaque release majeure, un test "use case réel" :

1. **Test "froid"** : un utilisateur novice ouvre l'app pour la
   première fois. Combien de temps pour configurer Binance + lancer
   un backtest ? Cible : **< 5 minutes**.

2. **Test "vie réelle"** : utiliser le bot pendant 1 journée
   normale (vérifier l'app le matin, le midi, le soir). Y a-t-il
   un moment où je ne comprends pas ce qui se passe ? Cible :
   **0 confusion**.

3. **Test "stress"** : provoquer un échec (clés API invalides,
   réseau coupé). Le message d'erreur permet-il de comprendre et
   résoudre ? Cible : **résolution en < 2 minutes** sans aide.

4. **Test "screenshot"** : prendre une capture aléatoire de l'app.
   Toutes les infos critiques sont-elles visibles ? Cible : **oui**.

---

## Onboarding wizard (premier lancement)

Lors du **tout premier lancement** de l'app (DB vide, aucune config),
un wizard guidé en **4 étapes** doit s'afficher. **Zéro friction**,
**zéro savoir technique requis**.

### Étape 1/4 — Bienvenue

**Visuel** : logo Emeraude + texte d'accueil

```
Bienvenue dans Emeraude.

Emeraude est ton trader crypto autonome. Il analyse le marché 24/7
et trade pour toi sur ton compte Binance.

Avant de commencer, on a besoin de 3 informations :
  1. Tes clés API Binance (lecture + trading)
  2. Le budget que tu lui alloues (en USDT)
  3. Confirmer le démarrage

Ça prend moins de 5 minutes.

[ Commencer → ]
```

### Étape 2/4 — Connexion Binance

**Visuel** : 2 champs API + lien d'aide + bouton de test

```
Connexion à ton compte Binance

1. Connecte-toi sur binance.com
2. Va dans "API Management"
3. Crée une nouvelle clé API
4. ✅ Active "Read" et "Trade"
5. ❌ NE PAS activer "Withdraw"
6. Copie-colle ici :

[Champ : Clé API Binance         ]
[Champ : Secret API (caché)      ]

[Tester la connexion]
[Aide : comment créer une clé →]

← Retour                  Suivant →
```

**Logique** :
- Si test échoue : message d'erreur précis (cf. `_test_binance`
  diagnostic 2 étapes)
- Si test OK : afficher solde Binance + bouton "Suivant"
- Si la clé a "Withdraw" activé : refus + message d'avertissement
  (cf. doc 09 sécurité)

### Étape 3/4 — Allocation du budget

**Visuel** : un champ + explication des 2 sous-portefeuilles

```
Combien tu alloues au bot ?

Emeraude va répartir ce capital en 2 sous-portefeuilles automatiquement :

🔵 Actif    : capital de travail (le bot trade avec)
🟢 Réserve  : sécurisation des gains (USDT, intouché)

Au début, 100 % en Actif. À mesure que le bot gagne, il transfère
progressivement vers la Réserve pour sécuriser tes bénéfices.

[Champ : Budget en USDT  →  20.00]

Note : le bot peut théoriquement perdre 100 % de ce budget. N'alloue
       que ce que tu acceptes de perdre.

← Retour                  Suivant →
```

### Étape 4/4 — Confirmation et démarrage

**Visuel** : récapitulatif + double confirmation argent réel

```
Récapitulatif avant démarrage

Compte Binance      : Connecté ✅
Solde sur Binance   : $130.45
Budget alloué bot   : $20.00
Mode                : RÉEL (argent vrai)

Le bot va :
  • Lancer son premier cycle d'analyse dans 60 secondes
  • Cycle suivant toutes les 60 minutes
  • Notifications quotidiennes via Telegram (à configurer)
  • Rapport hebdomadaire avec skim profit
  • Tu peux l'arrêter à tout moment via le bouton Emergency Stop

[ ⚠ Je comprends et j'active le bot ]

(Ce bouton demande une confirmation par double-tap.)

← Retour
```

**Après cette étape** : redirection vers le Dashboard, le bot est
actif.

### Ce que le wizard NE demande JAMAIS

L'utilisateur ne doit **jamais** être confronté à :
- Choisir une stratégie
- Régler des paramètres techniques (min_score, R/R, etc.)
- Activer ou non un filtre
- Comprendre RSI / MACD / Bollinger
- Choisir un timeframe
- Configurer un exchange autre que Binance

**Tous ces choix sont pré-réglés** avec la config champion validée
(cf. doc 04). L'utilisateur peut les modifier plus tard via Config
en mode "Avancé" (caché par défaut).

---

## Mode "Explication" (opt-in)

> Pour les utilisateurs curieux qui veulent **comprendre** ce que le
> bot fait, sans devoir le configurer.

### Principe

Sur chaque écran, un **bouton discret "ℹ Pourquoi ?"** ou
"Explication" en bas à droite révèle un panneau contextuel.

### Exemples par écran

#### Sur Dashboard, panneau "Pourquoi cette opportunité ?"

```
🎯 Top opportunité : SOL ACHAT FORT (65%)

Pourquoi le bot recommande SOL ?

  ✓ RSI à 28 → coin survendu, rebond probable
  ✓ MACD croise au-dessus de la signal line → momentum haussier
  ✓ Prix au-dessus de l'EMA 50 → tendance long terme positive
  ✓ Volume +35 % vs moyenne 20j → confirmation
  ✓ Pas de support cassé récemment

  Score combiné : 65/100
  R/R proposé : 2.3:1
  Position recommandée : ~5 USD si tu décides d'acheter

[Comprendre les indicateurs →]
[Pourquoi je vois ce signal ?]
```

#### Sur Portfolio, panneau "Pourquoi ce skim ?"

```
💰 Skim de cette semaine : 0.92 USDT → Réserve

Pourquoi 0.92 USDT (50 %) ?

  Tu es au palier P2 — Croissance.
  Ton capital total ($24.30) dépasse 1.2× ton capital initial ($24.00).
  Au palier P2, le bot transfère 50 % des gains hebdomadaires en
  Réserve pour sécuriser tes bénéfices.

  Gains de la semaine : 1.83 USDT
  Skim (50 %)         : 0.92 USDT → Réserve
  Réinvesti (50 %)    : 0.91 USDT (reste dans Actif)

  Prochain palier (P3) : à $40 de capital total.
```

#### Sur Signaux, panneau "Pourquoi le bot a skipé ETH ?"

```
ETH skipped — pourquoi ?

  Score : 38 (en dessous du seuil min_score = 45)
  Raison principale : RSI à 52 (zone neutre, pas de signal fort)

  Le bot ne prend que les signaux suffisamment forts pour avoir une
  espérance positive après frais (0.3 % par trade).
```

### Niveau de détail progressif

Le panneau "Explication" a 3 niveaux :
- **🟢 Simple** (par défaut) : phrases en langage courant
- **🟡 Détaillé** : avec valeurs des indicateurs
- **🔴 Technique** : formules, code, audit JSON

L'utilisateur choisit son niveau dans Config → "Niveau de
verbosité explications".

---

## Notifications proactives (niveau entreprise)

> L'app **prévient** l'utilisateur des événements importants, sans
> qu'il ait à ouvrir l'app pour vérifier.

### Cycle quotidien (Telegram)

Chaque jour à 22:00 UTC, si Telegram configuré :

```
📊 Emeraude — Aujourd'hui

🤖 Bot : ACTIF (cycle #1247)
💰 Capital : $24.30 (+0.42 USDT, +1.8 %)
📈 Trades : 1 exécuté (BTC, +0.42 USDT)
📊 Marché : BULL (BTC +3.2 %)
🟢 Tout va bien
```

### Alertes ponctuelles

Le bot envoie une notification quand :

- 🟢 **Trade gagnant fermé** (TP atteint) avec P&L
- 🔴 **Trade perdant fermé** (SL atteint) avec leçon apprise
- 🚨 **Circuit Breaker activé** (TRIGGERED ou FROZEN)
- 💰 **Skim hebdomadaire effectué** (récapitulatif)
- 📈 **Nouveau palier atteint** (P0 → P1, etc.)
- ⚠️ **Connexion Binance perdue** > 30 min
- 📅 **Rapport hebdomadaire** dimanche soir
- 🛡 **Suggestion d'audit** (mensuel : "ça fait 30 jours, vérifie tes
  permissions Binance")

### Fréquence raisonnable

L'utilisateur ne doit **pas être spammé**. Règles :
- Maximum 1 notification non-critique / heure
- Maximum 5 notifications / jour en mode normal
- Critique (Circuit Breaker, perte connexion) : illimité mais clair

L'utilisateur peut **régler** la verbosité dans Config → "Notifications" :
- Toutes (recommandé)
- Seulement critiques
- Seulement quotidien
- Aucune (déconseillé)

---

## États visuels de l'app (UX state machine)

L'app a **4 états visuels** distincts, instantanément reconnaissables :

### 🟢 État "Actif"
- Couleur principale : vert émeraude
- Header : "🤖 Bot actif — cycle #N"
- L'utilisateur n'a rien à faire

### 🟡 État "Paramétrage"
- Couleur principale : orange
- Header : "Configuration en cours — finalise pour activer le bot"
- L'utilisateur doit compléter quelque chose

### 🔵 État "Pause"
- Couleur principale : bleu
- Header : "Bot en pause — Tape pour activer"
- L'utilisateur a délibérément arrêté le bot

### 🔴 État "Urgence"
- Couleur principale : rouge
- Header : "🚨 Action requise"
- Quelque chose nécessite l'attention immédiate (Circuit Breaker,
  réseau perdu > 1h, etc.)

L'icône de l'app sur Android peut **également refléter l'état** via
un badge de notification (🟢 / 🟡 / 🔴).

---

## Human override : interventions manuelles sans casser le bot

Emeraude est autonome, mais l'utilisateur reste **propriétaire ultime
de son capital**. Il doit pouvoir intervenir manuellement sans que le
bot entre en conflit avec la state machine.

### 4 cas d'override prévus

| # | Cas | Action utilisateur | Réaction Emeraude |
|:-:|---|---|---|
| H1 | **Fermeture manuelle d'une position** | Tap "Fermer maintenant" sur une carte position | Annule SL/TP serveur, place market sell, marque la position `closed_manually` dans DB, log audit `manual_exit` |
| H2 | **Pause totale du bot** | Toggle "Mettre en pause" | Aucun nouveau cycle d'entrée, gestion exits **conservée** (SL/TP serveur tournent toujours), bandeau jaune "EN PAUSE" |
| H3 | **Stop d'urgence (kill switch)** | Bouton rouge "STOP TOUT" + double-confirmation biométrique | Annulation de tous les SL/TP pendants, fermeture market de toutes positions, bot freeze total, état "STOP UTILISATEUR" persisté |
| H4 | **Modification d'un SL en cours** | Slider dans la carte position | Re-place le SL serveur côté Binance avec le nouveau prix, log audit `manual_sl_change` |

### Règle absolue : pas de conflit silencieux

Toute action manuelle qui modifie l'état d'une position doit :

1. **Apparaître dans `audit_log`** avec type `manual_*`
2. **Être visible immédiatement** dans le journal des trades (badge "M" pour manuel)
3. **Bloquer pendant 30 s** toute action automatique sur la même
   position (anti-race condition)
4. **Synchroniser l'état** : après l'action, refetch positions Binance
   pour confirmer

### Anti-pattern à éviter

L'erreur classique : l'utilisateur ferme manuellement BTC sur l'app
Binance officielle, mais Emeraude ignore et garde la position dans sa
DB → SL fantôme, double-comptage.

**Garde-fou** : à chaque cycle, **réconciliation** des positions DB vs
Binance API. Toute divergence détectée :
- Position en DB absente de Binance → marquée `closed_externally` avec PnL reconstitué via trades history
- Position dans Binance absente de DB → ingérée comme position
  manuelle avec tag `imported_external`
- Notification utilisateur si > 1 divergence par jour (suspicion bug)

### UX du STOP d'urgence

Le bouton rouge n'est **jamais en première ligne** (risque de tap
accidentel). Workflow :

```
Settings → "Avancé" → "Arrêt d'urgence"
    ↓
"Cette action va fermer toutes les positions au prix marché.
 Pertes potentielles si gap. Continuer ?"
    ↓
[Annuler]  [Confirmer (biométrique)]
    ↓ (si confirmé)
Animation rouge 3 s : "Fermeture en cours..."
    ↓
Écran final : nombre de positions fermées, PnL réalisé total
```

→ Réversibilité : l'utilisateur peut redémarrer le bot après, mais le
capital est figé tant qu'il ne réautorise pas explicitement.

### Critères mesurables (H1-H4)

| # | Critère | Validation |
|:-:|---|---|
| H1 | Tous les overrides loggés en `audit_log` type `manual_*` | audit query |
| H2 | Réconciliation DB ↔ Binance à chaque cycle | audit log + test |
| H3 | 0 conflit auto/manuel non détecté en 30 jours | audit query |
| H4 | Stop d'urgence ferme 100 % positions ≤ 30 s | test E2E |

---

## Anti-patterns UX interdits

| ❌ Anti-pattern | Pourquoi c'est mauvais |
|---|---|
| Texte tronqué à `[:5]` qui cache l'info | "ACHAT FORT" → "ACHAT" indistinguable de "ACHAT" simple |
| Bouton avec emoji sans label texte | Si l'emoji ne rend pas, le bouton est inutilisable |
| Status hors champ visible (en bas alors que action en haut) | L'utilisateur ne voit pas le feedback |
| Modal sans bouton close visible | Frustration |
| Loading spinner sans timeout / sans erreur | App freeze sans explication |
| Saisie sans validation immédiate | L'utilisateur découvre l'erreur après save |
| Confirmation par alert "OK / Cancel" | Trop générique, pas de contexte |
| Couleur unique pour succès et avertissement | Confusion |
| Police trop petite (< 11 dp) | Illisible sur petit écran |
| Animation longue (> 300 ms) | Sensation de lenteur |

---

*v1.0 — 2026-04-25*
