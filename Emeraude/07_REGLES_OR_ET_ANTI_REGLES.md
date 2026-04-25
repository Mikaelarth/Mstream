# 07 — Règles d'Or et Anti-Règles

> Document court, sec, **inviolable**. Toute itération qui contredit
> ces règles est **rejetée**, peu importe sa sophistication.

---

## ⛔ Anti-règles (ce qu'on NE FAIT JAMAIS)

### A1. Pas de fonctionnalité fictive

Si une fonctionnalité ne marche pas en runtime réel, elle n'est pas
"presque finie" — elle est **cassée**. Pas de "Coming soon" affiché à
l'utilisateur, pas de placeholder.

**Test** : un utilisateur clique sur le bouton, est-ce que ça fait
quelque chose d'utile ? Si non, le bouton n'a pas sa place dans
l'app livrée.

### A2. Pas de mock dans le code de production

Mocks réservés à `tests/`. En prod, soit on a la vraie data, soit on
gère explicitement le cas "pas de data" (avec message clair).

### A3. Pas de chiffre marketing non vérifié

Phrases interdites :
- "Niveau hedge fund" (sans Sharpe > 1 prouvé)
- "Le meilleur des meilleurs" (sans comparaison documentée)
- "Performances exceptionnelles" (sans chiffres)
- "Rendement garanti" (rien n'est garanti en trading)

### A4. Pas de "ACHAT FORT" sur trade à espérance négative

Si R/R < 1.5, le signal est **dégradé en HOLD**, pas affiché comme
"opportunité".

### A5. Pas d'activation argent réel sans confirmation explicite

Tous les toggles qui activent du trading réel exigent un **double-tap
avec délai 5 secondes** et un message qui montre **le montant en
jeu**.

### A6. Pas de cloud sans permission utilisateur explicite

Aucune donnée ne sort du téléphone vers un serveur tiers (sauf API
Binance officielle). Si on ajoute du cloud (backup, sync), c'est
**opt-in explicite** avec affichage de quelle data part où.

### A7. Pas de TODO/FIXME laissé en code livré

Si quelque chose est incomplet, soit on le finit, soit on le retire,
soit on documente dans `Emeraude/06_ROADMAP_ET_CRITERES.md` comme
"chantier ouvert" — pas en commentaire au milieu du code.

### A8. Pas de cache d'erreur silencieux

`except Exception: pass` ou `return None` est interdit sans :
- `logger.exception(...)` minimum
- OU exception spécifique justifiée
- OU commentaire expliquant pourquoi le silence est sûr

### A9. Pas de divergence UI vs code

Si l'UI affiche "Cycle 5 minutes" mais le code fait 60 minutes, c'est
un **bug**, pas une "approximation". À fixer immédiatement.

### A10. Pas de calibration paramétrique présentée comme "alpha"

Trouver un paramètre qui donne Sharpe +2 sur 60 jours **n'est pas un
edge**. Seul le **walk-forward** prouve un edge robuste.

### A11. Pas de capital dans le code

Le capital de l'utilisateur (20 USD) **n'est pas hardcodé**. Lu
dynamiquement depuis la DB via `database.get_setting`. Permet à
l'utilisateur de changer sans toucher au code.

### A12. Pas d'augmentation de capital sans 30j de track record

Pour passer d'un palier de capital au suivant (cf. doc 06), il faut
**30 jours minimum** de tracking record positif au palier actuel.

### A13. Pas de modification de la stratégie sans walk-forward

Avant de pousser un changement à la logique de signaux ou aux
filtres, il **faut** mesurer en walk-forward (10 fenêtres minimum).
Une mesure backtest unique ne suffit pas.

### A14. Pas d'ajout de fonctionnalité sans test pytest

Toute nouvelle fonction publique doit avoir au moins **un test
unitaire** dans `tests/`. La couverture actuelle (311 tests) est un
acquis à préserver.

### A15. Pas d'emoji dans les éléments fonctionnels critiques

Les emojis ne rendent pas dans Roboto Android. Réservés aux titres
décoratifs, pas aux boutons / labels d'action / messages d'erreur.

---

## ✅ Règles d'Or (ce qu'on FAIT TOUJOURS)

### R1. Mesurer avant d'optimiser

Avant de "améliorer" quelque chose, mesurer son état actuel. Sinon
on ne sait pas si l'optimisation a aidé ou nui.

### R2. Une variable changée à la fois

Quand on calibre, on change **une seule chose à la fois**, on
mesure, on garde si meilleur, sinon revert. C'est la base du
A/B testing.

### R3. Reproduire les bugs avant de les fixer

Quand on trouve un bug, on écrit un test qui le reproduit (ou on
décrit la repro runtime), **puis** on fixe. Sans repro, on ne sait
pas si on a vraiment fixé.

### R4. Toast central > status bar en bas

Pour les feedbacks d'action : toast central auto-dismiss
(`screens/toast.py`). Le user voit immédiatement le résultat sans
scroll.

### R5. Validation runtime > tests pytest seuls

Pour tout changement UI ou réseau Android, le pytest seul ne suffit
pas. Soit lancer desktop OU rebuild APK + capture user.

### R6. Honnêteté > marketing

Si Sharpe = -0.91, le dire. Pas "résultats encourageants à confirmer".
La confiance long-terme se gagne par la transparence.

### R7. Persistance Android-safe par défaut

Tous les fichiers persistants passent par `core/paths.py`. Pas de
hardcoded path style `Path(__file__).parent.parent.parent`.

### R8. SSL context partagé pour HTTPS

Tout `urllib.request.urlopen` doit recevoir `context=core.net.SSL_CTX`.
Sinon échec silencieux sur Android.

### R9. Audit trail pour chaque décision

Chaque décision du bot (entrée, sortie, skip) génère un événement
`audit_log` JSON queryable. Permet le post-mortem.

### R10. Circuit Breaker non-bypass

Aucun chemin de code ne contourne le Circuit Breaker. S'il dit
TRIGGERED, le bot s'arrête, point.

### R11. Lecture du dossier Emeraude au début de chaque session

Toute personne (humaine ou IA) qui reprend ce projet **doit lire**
`Emeraude/00_LISEZ_MOI.md` et les docs liés avant tout commit.

### R12. Mise à jour de Emeraude après chaque pivot

Si une décision majeure change le périmètre ou la mission, le doc
correspondant dans `Emeraude/` est mis à jour **dans le même commit**.

### R13. Retour sur investissement temps prouvé

Avant d'attaquer une optimisation qui prendra > 1h, estimer
l'impact attendu chiffré. Si l'effort > impact, ne pas faire.

### R14. Le 20 USD réel > Sharpe théorique

Toute décision est jugée à l'aune de "ça aide-t-il les 20 USD réels
de l'utilisateur ?". Pas "ça aide-t-il un benchmark théorique ?".

---

## ⚖️ Hiérarchie de priorité (en cas de conflit)

Quand deux règles entrent en conflit, on suit cet ordre :

1. **Sécurité du capital utilisateur** > tout le reste
   (Circuit Breaker, confirmation argent réel, persistance, etc.)

2. **Sécurité des secrets utilisateur** > performance
   (Clés API masquées, chiffrement, KeyStore)

3. **Honnêteté des messages** > marketing visuel
   (Pas de mensonge sur Sharpe, ROI, etc.)

4. **UX fluide** > sophistication algorithmique
   (Mieux vaut un bot moyen utilisable qu'un excellent illisible)

5. **Apprentissage continu** > stratégie figée
   (Pilier #2 : le bot doit évoluer)

6. **Tests verts** > velocity
   (Une régression cachée vaut moins qu'un trou de couverture)

---

## Cas pratiques

### Cas A : "Je voudrais ajouter du machine learning avec scikit-learn"

❌ Refusé. Viole **A14** (pas de dépendance scientifique lourde, augmente
APK de 100+ MB, build Buildozer cassé).

Alternative acceptée : implémenter l'algo en pure Python (comme
Thompson Sampling actuel).

### Cas B : "Le walk-forward dit Sharpe -0.5 mais on lance quand même"

❌ Refusé. Viole **A4** (espérance négative) et **A10** (pas
d'optimisation paramétrique faisant croire à un edge).

Alternative : retravailler la stratégie jusqu'à walk-forward Sharpe ≥ 0.5.

### Cas C : "On affiche des chiffres de backtest passé pour rassurer le user"

⚠️ Conditionnel. OK si :
- Les chiffres sont **vrais** et calculés en live
- L'UI précise "BACKTEST 90j passé" (pas "Performance du bot")
- Le walk-forward verdict est aussi affiché

❌ Refusé si on cache les pertes ou si on présente backtest comme
performance live.

### Cas D : "On bypass le Circuit Breaker pour tester"

❌ Refusé. Viole **R10**. À la limite, ajouter un mode "debug" qui
log mais n'exécute pas, **jamais** un mode qui bypass et exécute.

### Cas E : "On ajoute un mode trading manuel à côté du bot"

⚠️ Conditionnel. Acceptable si :
- Le mode manuel est **distinct** du bot (pas de confusion)
- Pas de mensonge sur les responsabilités (qui a pris le trade)
- L'audit trail distingue clairement

---

*v1.0 — 2026-04-25*
