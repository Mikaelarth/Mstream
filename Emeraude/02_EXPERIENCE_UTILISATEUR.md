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
