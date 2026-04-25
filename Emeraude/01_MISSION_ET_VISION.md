# 01 — Mission et Vision

## La mission unique et non-négociable

> **Faire fructifier 20 USD de façon autonome sur smartphone Android,
> 100 % en local, avec une expérience utilisateur irréprochable, et
> un agent qui s'améliore en s'entraînant.**

Cette phrase résume tout. Si une décision contredit cette phrase, elle
est rejetée — peu importe sa sophistication technique.

---

## Décomposition mot par mot

### "Faire fructifier 20 USD"

- **Capital concret** : pas un benchmark théorique, pas un Sharpe sur
  10 ans de data, pas un concours académique.
- **Mesure du succès** : ROI réel **après frais** sur compte Binance
  réel après 30 jours, 90 jours, 1 an.
- **Critère minimal** : le bot ne doit PAS perdre plus que les frais
  cumulés. Tout au-dessus est un bonus.
- **Croissance composée** : le bot réinvestit ses gains. Pas de
  retrait automatique.

### "De façon autonome"

- L'utilisateur ne valide **rien manuellement** une fois le bot lancé.
- Pas de mode "shadow" ou "approve each trade" — le bot exécute ses
  ordres Binance tout seul.
- L'utilisateur garde un **kill switch** (Emergency Stop) pour tout
  arrêter d'un tap.

### "Sur smartphone Android"

- **Mobile-first** : l'app principale est sur Android. Le desktop est
  pour le développement uniquement.
- **APK Android** distribué via GitHub Actions (artifact debug) ou
  Releases (production).
- **Tourne en arrière-plan** sans tuer la batterie déraisonnablement.
- **Survit aux redémarrages** du téléphone (auto-recovery via
  checkpoint).

### "100 % en local"

- **Aucune donnée ne sort** du téléphone vers un serveur tiers
  (sauf API Binance officielle pour exécuter les ordres).
- **Clés API chiffrées** localement (PBKDF2-SHA256 + sel privé).
- **Pas de cloud** pour les sauvegardes (sauf backup chiffré opt-in
  vers le storage de l'utilisateur — Drive personnel par exemple).
- **Pas d'abonnement** : tout est gratuit après installation.

### "Expérience utilisateur irréprochable"

Voir [02_EXPERIENCE_UTILISATEUR.md](02_EXPERIENCE_UTILISATEUR.md) en
détail. Résumé :
- Aucune action ne doit demander à l'utilisateur de réfléchir.
- Tous les états critiques (position ouverte, P&L, alertes) sont
  visibles d'un coup d'œil.
- Tous les feedbacks (toast, notif) sont clairs, immédiats, précis.
- L'app est utilisable d'une main sur smartphone.

### "Agent qui s'améliore en s'entraînant"

Voir [03_AGENT_INTELLIGENT_EVOLUTIF.md](03_AGENT_INTELLIGENT_EVOLUTIF.md)
en détail. Résumé :
- Chaque trade fermé alimente une mémoire d'apprentissage.
- Les poids des stratégies sont ré-estimés à chaque trade
  (Thompson Sampling).
- Les paramètres (min_score, min_rr, etc.) sont ajustés selon la
  performance récente.
- L'utilisateur **voit** cette évolution dans l'UI.

---

## Pourquoi ce projet existe

L'utilisateur a constaté :

1. **Le marché crypto tourne 24/7 mais lui non.**
   La peur, la cupidité et la fatigue sabotent ses décisions de
   trading manuel.

2. **Les solutions existantes sont insatisfaisantes.**

   | Concurrent | Limite |
   |---|---|
   | 3Commas, Cryptohopper | Abonnement mensuel + cloud + données envoyées à des tiers |
   | Pionex | Stratégies grid figées, pas adaptatives |
   | Trality | Belle plateforme mais limitée en custom |
   | Bitsgap, Coinrule | Idem, dépendance cloud |

3. **Il veut souveraineté et personnalisation.**
   Code lisible, modifiable, **qui lui appartient**.

4. **Il accepte d'apprendre par l'expérience réelle.**
   Pas de phase paper de 3 mois en pré-production. 20 USD réels,
   tout de suite.

---

## Vision à 1 an

Dans 12 mois, le bot doit avoir :

- ✅ **Tourné sans crash** sur le téléphone
- ✅ **Pris au moins 100 trades** réels avec audit trail complet
- ✅ **Win rate net après frais** > 35 % (= breakeven avec R/R 2:1)
- ✅ **Sharpe ratio annualisé** > 0.8 sur 1 an réel (pas backtest)
- ✅ **Drawdown max** < 20 % sur la période
- ✅ **Évolué visiblement** : les poids des stratégies ne sont plus
  ceux du jour 1 ; le bot a appris quelles stratégies marchent dans
  quels régimes pour ce profil de marché et ce capital.
- ✅ **L'utilisateur l'utilise quotidiennement** sans friction (UX
  validée par usage continu).

Si le bot atteint ces 7 critères en 12 mois, le projet est un
**succès**. Si le bot perd 100 % du capital pendant que l'app est belle,
c'est un **échec**.

---

## Vision à 3-5 ans (aspiration, pas engagement)

Si l'utilisateur le souhaite, le projet peut évoluer vers :
- Open-sourcer pour la communauté
- Multi-utilisateurs (chaque utilisateur a son bot)
- Multi-exchanges (Coinbase, Kraken)
- Capital plus important (1k$ → 10k$)
- Stratégies plus sophistiquées (DeFi, options)

**Ce n'est pas l'engagement actuel.** Aujourd'hui : 20 USD, Binance,
Android, en local.

---

## Ce que ce projet n'est PAS

Pour éliminer toute ambiguïté :

| ❌ Ce projet n'est pas | Pourquoi |
|---|---|
| Une démo pédagogique | C'est un outil financier réel |
| Un concours de Sharpe ratio | Le réel sur 30j vaut plus qu'un beau backtest |
| Une plateforme SaaS | Pas de cloud, pas d'autres utilisateurs |
| Un produit générique | C'est l'outil personnel d'UN utilisateur précis |
| Une expérience open-source à la 3Commas-killer | Ça pourrait l'être, mais ce n'est pas l'objectif maintenant |
| Un bot qui suit aveuglément des règles fixes | C'est un agent qui **évolue** par apprentissage |

---

*v1.0 — 2026-04-25*
