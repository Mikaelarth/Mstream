# 💎 Emeraude — Cadre du projet

> **Document maître**, à lire en début de chaque session de travail
> sur ce projet (humaine ou IA).
>
> Versionné dans le repo. Toute pivot majeur passe par mise à jour de
> ces documents — pas de décision tacite hors de ce dossier.

---

## Pourquoi Emeraude ?

L'émeraude symbolise :
- **La constance** (couleur stable, dure dans le temps)
- **La précision** (pierre taillée, pas de flou)
- **La valeur** (rare, précieuse, ne se brade pas)

C'est ce qu'on attend de ce projet : **un outil constant, précis,
précieux** — pas une démo bricolée.

---

## Structure du dossier

| # | Document | Rôle |
|:-:|---|---|
| 00 | [LISEZ_MOI](00_LISEZ_MOI.md) | Vue d'ensemble (vous y êtes) |
| 01 | [MISSION_ET_VISION](01_MISSION_ET_VISION.md) | Pourquoi le projet existe, l'objectif unique |
| 02 | [EXPERIENCE_UTILISATEUR](02_EXPERIENCE_UTILISATEUR.md) | **Pilier #1** : charte UX, onboarding, mode explication |
| 03 | [AGENT_INTELLIGENT_EVOLUTIF](03_AGENT_INTELLIGENT_EVOLUTIF.md) | **Pilier #2** : apprentissage continu, évolution |
| 04 | [STRATEGIES_TRADING](04_STRATEGIES_TRADING.md) | Stratégies multiples + **Architecture Actif/Réserve** |
| 05 | [ARCHITECTURE_TECHNIQUE](05_ARCHITECTURE_TECHNIQUE.md) | Stack, modules, contraintes techniques |
| 06 | [ROADMAP_ET_CRITERES](06_ROADMAP_ET_CRITERES.md) | 6 paliers, 40 critères de terminaison (T1-T20 + E1-E20) |
| 07 | [REGLES_OR_ET_ANTI_REGLES](07_REGLES_OR_ET_ANTI_REGLES.md) | Ce qu'on fait, ce qu'on ne fait jamais |
| 08 | [PROTOCOLE_ITERATION](08_PROTOCOLE_ITERATION.md) | Comment chaque future session doit se dérouler |
| 09 | [NIVEAU_ENTREPRISE](09_NIVEAU_ENTREPRISE.md) | **Pilier #3** : SLA, robustesse, sécurité hardware |
| 10 | [INNOVATIONS_ET_EDGE](10_INNOVATIONS_ET_EDGE.md) | **Pilier #4** : 12 lacunes du trading retail + 12 réponses concrètes + champion lifecycle |
| 11 | [INTEGRITE_DONNEES](11_INTEGRITE_DONNEES.md) | Anti look-ahead, survivorship, qualité bougies, reproductibilité |

---

## Lecture rapide pour reprendre le projet

Tu n'as que 5 minutes ? Lis dans cet ordre :

1. **01_MISSION_ET_VISION** (la raison d'être) — 2 min
2. **06_ROADMAP_ET_CRITERES** §"État actuel" (où on en est) — 1 min
3. **07_REGLES_OR_ET_ANTI_REGLES** (les contraintes inviolables) — 2 min

Tu as 30 minutes ? Lis tout le dossier dans l'ordre numérique.

---

## Profil utilisateur

Le **propriétaire du repo et seul utilisateur** :

- Compte Binance déjà existant
- Capital total : **30 USD**, dont **20 USD alloués au bot**
- Tolérance perte : 100 % (20 USD)
- Délai trading réel : immédiatement après installation
- Plateforme primaire : **smartphone Android**
- Préférences :
  - **UX irréprochable** (fluide, claire, sans friction)
  - **Bot qui s'améliore avec le temps** (apprentissage continu)
  - **Multi-stratégies adaptatives** (le bot choisit l'algo selon le marché)

---

## Les quatre piliers de qualité (2026-04-25)

Ce projet repose sur **quatre piliers** non-négociables :

### 🎨 Pilier #1 — UX (document 02)
Fluide, ergonomique, facile. Aucun écran ne doit demander à l'utilisateur
de réfléchir à comment l'utiliser. Tous les états critiques doivent être
visibles d'un coup d'œil. Voir [02_EXPERIENCE_UTILISATEUR](02_EXPERIENCE_UTILISATEUR.md).

### 🧠 Pilier #2 — Agent évolutif (document 03)
Le bot **apprend de chaque trade** (gagnant ou perdant), ajuste
**automatiquement** les poids de ses stratégies et ses paramètres,
et devient **mesurablement meilleur** dans le temps. Voir
[03_AGENT_INTELLIGENT_EVOLUTIF](03_AGENT_INTELLIGENT_EVOLUTIF.md).

### 🏛 Pilier #3 — Niveau Entreprise (document 09)
SLA d'uptime ≥ 99 %, latence ≤ 30 s, mémoire ≤ 200 MB, batterie
≤ 3 %/24h. Robustesse face aux 5 modes de défaillance documentés.
Voir [09_NIVEAU_ENTREPRISE](09_NIVEAU_ENTREPRISE.md).

### ⚔️ Pilier #4 — Edge concurrentiel (document 10)
Pas de fake IA. **12 lacunes structurelles** du trading retail
identifiées, **12 réponses concrètes** implémentables en pure Python :
calibration, drift detection, tail risk, meta-gate, exécution
intelligente, mémoire long-terme. Voir
[10_INNOVATIONS_ET_EDGE](10_INNOVATIONS_ET_EDGE.md).

Ces quatre piliers s'ajoutent à la mission de fond (faire fructifier
20 USD réels en local sur Android).

---

## Comment ce dossier est entretenu

- **Auteur principal** : itérations IA + revues utilisateur
- **Mise à jour** : après chaque pivot majeur (changement de stratégie,
  ajout de fonctionnalité critique, correction de cap)
- **Versioning** : git. Pour voir l'évolution :
  `git log --oneline -- Emeraude/`
- **Lecture obligatoire** : début de chaque session, avant tout commit

---

*v1.0 — 2026-04-25*
