# 08 — Protocole d'Itération

> Comment chaque future session de travail sur ce projet doit se dérouler.
> Vaut pour humain et pour IA. Versionné dans le repo.

---

## Format d'invocation d'une itération

L'utilisateur demande une itération en utilisant l'une de ces formules :

```
itération suivante Emeraude
```

ou plus explicitement :

```
fais une itération Emeraude. Lis Emeraude/, identifie l'objectif
chiffré le plus impactant, mesure avant/après, et reporte honnêtement.
```

L'agent (IA ou humain) répond en commençant **directement par la
Phase 1** ci-dessous, sans préambule.

---

## Les 6 phases obligatoires

### Phase 1 — Lecture (5 min max)

Lire dans cet ordre :

1. `Emeraude/00_LISEZ_MOI.md`
2. `Emeraude/06_ROADMAP_ET_CRITERES.md` (état courant + critères)
3. `Emeraude/07_REGLES_OR_ET_ANTI_REGLES.md`
4. `git log --oneline -10` (commits récents)
5. `docs/PROJECT_STATE.md` (historique itérations)

**Output attendu** : compréhension de :
- Où on en est (combien de critères ✅)
- Ce qui a été fait dans les 10 derniers commits
- Quelles règles d'or/anti-règles s'appliquent

### Phase 2 — Identifier UN objectif chiffré

**Pas** : "améliorer le bot", "corriger des bugs", "polir l'UI".

**Mais** :
- "Faire passer le critère de terminaison #10 (consistency walk-forward)
  de 40 % à 50 %"
- "Créer l'écran IA / Apprentissage (critère P3.1)"
- "Réduire le nombre de SL hits de 100 % à < 80 % en backtest 90j"

**Règle** : un objectif **mesurable** avec un chiffre **avant** connu
et un chiffre **après** vérifiable.

L'agent **annonce explicitement** l'objectif au user en début
d'itération :

```
Objectif de cette itération :
  - Critère ciblé : #N
  - Mesure avant : X
  - Cible : Y
  - Méthode envisagée : ...
```

### Phase 3 — Diagnostic / hypothèse

Avant de coder, comprendre. Pour le bug ou le manque ciblé :

- **Quel est le mécanisme racine** ?
- **Quelles 1-3 hypothèses peuvent expliquer le problème** ?
- **Comment les départager** par mesure ?

Output : un commentaire dans le rapport d'itération expliquant
**pourquoi** la solution choisie est la bonne, pas juste **quoi**.

### Phase 4 — Implémentation chirurgicale

Règles :
- **Une variable changée à la fois** (cf. R2)
- **Reproduire le bug d'abord** (cf. R3)
- **Pas de refactor opportuniste** non lié à l'objectif
- **Respecter le périmètre** (pas de "tant qu'on y est")
- **Test pytest minimum** pour toute nouvelle fonction (cf. A14)

### Phase 5 — Validation

Pour TOUT changement, vérifier :

#### 5.1 Tests pytest 100 % verts

```bash
cd MstreamTrader   # nom du dossier code (pour rappel : l'app s'appelle Emeraude, le dossier code historique reste MstreamTrader le temps du rename progressif)
py -3.12 -m pytest tests/ -q
# Doit afficher "311 passed" (ou plus si tests ajoutés)
```

#### 5.2 Mesure objectif après vs avant

L'objectif chiffré déclaré en Phase 2 est-il atteint ?

Output : ligne "Mesure après : Z" dans le rapport.

#### 5.3 Validation runtime si concerné

Si le changement touche :
- L'UI Kivy → tester desktop (lancer `py main.py`)
- L'APK Android → push + GitHub Actions APK + capture user
- Le réseau Android → SSL_CTX appliqué + idem capture user

**Pas de "ça devrait marcher"**.

#### 5.4 Pas de régression

```bash
# Vérifier qu'aucun autre test n'est cassé
py -3.12 -m pytest tests/ -q
# 0 tests rouges
```

### Phase 6 — Documentation et commit

#### 6.1 Update Emeraude si périmètre change

Si l'itération introduit une nouvelle règle, change un palier, modifie
les critères de terminaison → **mise à jour du fichier Emeraude
correspondant** dans le **même commit**.

#### 6.2 Update PROJECT_STATE.md

Ajouter une ligne pour cette itération :

```markdown
> - **Itération #N (date)** : <description courte>. Mesure avant: X,
>   après: Y. Critère #M: <statut>. <bugs trouvés/corrigés>.
```

#### 6.3 Commit message rigoureux

Format obligatoire :

```
<type>(<scope>): <résumé court de l'objectif>

ITÉRATION #N — <titre>

OBJECTIF
  Critère ciblé : #X
  Mesure avant : <valeur>
  Cible : <valeur>

DIAGNOSTIC / HYPOTHÈSE
  <pourquoi le problème, racine, alternatives écartées>

ACTIONS
  - Fix #1 : <quoi>
  - Fix #2 : <quoi>

MESURE APRÈS
  <valeur effective> — ✅ atteint / ❌ raté / 🟡 partiel

CRITÈRES DE TERMINAISON
  Avant : N/20 ✅
  Après : M/20 ✅
  Gagné : <critères>
  Perdu : <critères>

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

Types : `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `ci`.

#### 6.4 Push

```bash
git push
```

Vérifier que la CI passe (Tests + Build APK).

---

## Format de rapport en fin d'itération

Après le commit, l'agent répond au user avec ce format **strict** :

```markdown
# 📋 Rapport — Itération #N

## Objectif
- Critère ciblé : #X (<nom>)
- Mesure avant : <valeur>
- Cible : <valeur>

## Diagnostic
<3-5 lignes max sur la cause racine et l'hypothèse>

## Actions appliquées
| Action | Fichier | Effort |
|---|---|---|
| ... | ... | ... |

## Résultat mesuré
- Mesure après : <valeur>
- Verdict : ✅ atteint / ❌ raté / 🟡 partiel
- Pourquoi (si partiel/raté) : <explication>

## État critères de terminaison
- Avant : N/20 ✅
- Après : M/20 ✅
- Gagné : #X (<nom>)
- Perdu : <si applicable>

## Tests pytest
311/311 ✓ en X.Y secondes (ou +N nouveaux tests)

## CI
URL du run : <lien>
Statut : success / failure

## Prochaine itération suggérée
<Critère le plus impactant restant à attaquer>
```

---

## Quand s'arrêter ?

L'agent **s'arrête** uniquement quand :

1. **Tous les 20 critères de terminaison** sont ✅ (cf.
   `06_ROADMAP_ET_CRITERES.md`)

OU

2. **L'utilisateur le demande explicitement**

OU

3. **Un blocker insurmontable est rencontré** (manque de data, erreur
   externe, etc.) → l'agent l'identifie clairement et attend
   instructions.

L'agent **ne s'auto-déclare pas "fini"** sur un score < 20/20.

---

## Cas particuliers

### Cas : "L'agent ne sait pas par où commencer"

L'agent applique cet algorithme :
1. Lire `06_ROADMAP_ET_CRITERES.md` section "Tableau récapitulatif"
2. Identifier les critères 🔴 (pas ⚠️)
3. Pour chaque 🔴, estimer l'effort (en jours)
4. Pour chaque 🔴, estimer l'impact (combien de critères débloqués)
5. Choisir le ratio impact/effort le plus haut
6. Si égalité : prioriser sécurité > performance > UX

### Cas : "L'agent veut faire plusieurs choses"

**Refusé**. Une itération = un objectif. Si plusieurs objectifs :
plusieurs itérations en série, chacune avec son rapport.

Exception : refactoring nécessaire à l'objectif principal (genre
"fix bug X qui empêche d'attaquer le critère Y").

### Cas : "L'utilisateur ne répond pas"

L'agent ne fait pas tourner d'itérations en boucle de son propre
chef. Il attend une instruction explicite (`itération suivante`).

Exception : si l'agent a déjà commencé une itération et atteint
un blocker, il peut compléter le rapport et s'arrêter sans
nouvelle instruction.

### Cas : "La règle de 1 variable changée à la fois est trop lente"

**Pas de dérogation.** Si on change 5 variables en même temps et que
ça améliore, on ne sait pas laquelle a vraiment aidé. C'est de la
chance, pas de l'ingénierie.

Exception : refactoring purement structurel sans changement de
comportement (ex: renommage). Vérifier qu'aucun test ne rougit.

---

## Outils disponibles

### Local (développeur)

```bash
# Tests
py -3.12 -m pytest tests/ -q

# Backtest
py -3.12 run_backtest.py --days 90 --verbose

# Walk-forward optimization
py -3.12 optimize_params.py --days 90 --walk-forward

# Lancer l'app desktop
py -3.12 main.py
```

### CI

- Tests automatique sur push
- Build APK automatique sur push (artifact disponible 30 jours)
- Release APK sur tag `v*`

### Outils de mesure

- `core/metrics.py` : Sharpe, Sortino, Calmar, PF, expectancy
- `core/walk_forward.py` : robustesse hors-sample
- `core/audit.py` : query du trail JSON

---

## Mémoire entre sessions

L'agent IA n'a pas de mémoire propre entre sessions. La mémoire vit dans :

1. **Le repo git** (commits, history)
2. **Le dossier Emeraude** (cahier des charges)
3. **`docs/PROJECT_STATE.md`** (historique itérations)
4. **`MEMORY.md`** de l'agent (feedback durable utilisateur)

Tout nouveau travail commence par **lire ces sources** pour
récupérer le contexte (cf. Phase 1).

---

*v1.0 — 2026-04-25*
