# 11 — Intégrité des données & anti look-ahead

> Toutes nos métriques (Sharpe, walk-forward, ECE) **n'ont de valeur que
> si les données sous-jacentes sont propres et sans fuite d'information
> future**. Ce document formalise les garde-fous.
>
> **Principe absolu** : si la donnée est suspecte, la décision basée
> dessus est à jeter. Pas de "best effort".

---

## 1. Pourquoi ce document existe

Les bots qui meurent en silence partagent souvent la même cause racine :
- backtest brillant sur données contaminées (look-ahead bias)
- coin universe sélectionné a posteriori (survivorship bias)
- bougies manquantes silencieusement comblées avec extrapolation
- timestamps mal alignés (UTC vs locale)

**Emeraude refuse cette catégorie d'erreurs par construction.**

---

## 2. Les 6 sources de contamination

| # | Type | Exemple concret | Notre garde-fou |
|:-:|---|---|---|
| D1 | **Look-ahead bias** | Calculer un indicateur à T en utilisant le close de T+1 | Validation par décalage forcé |
| D2 | **Survivorship bias** | Backtester sur les top 10 d'aujourd'hui (qui ont survécu) | Univers gelé à la date de début |
| D3 | **Bougies corrompues** | Open=Close=High=Low (volume 0, marché fermé) | Détection + rejet ou flag |
| D4 | **Bougies manquantes** | Trou de 2h dans la série | Détection + interpolation transparente OU rejet |
| D5 | **Timezone mismatch** | Mélange UTC et locale dans la même série | Tout en UTC, jamais autrement |
| D6 | **Data revision** | Binance corrige une bougie a posteriori | Snapshot horodaté immuable |

---

## 3. Garde-fous par source

### D1 — Look-ahead bias (le plus dangereux)

**Règle absolue** : pour calculer une décision à l'instant T, on n'a
**aucun accès** aux données de timestamp ≥ T.

**Mise en œuvre** :

1. **API typée** : toute fonction qui prend une série temporelle reçoit
   en paramètre un `as_of: datetime`. Tout point ≥ `as_of` est filtré
   **dans la fonction**, pas en amont.

   ```python
   def compute_indicators(series: List[Bar], as_of: datetime) -> Dict:
       valid = [b for b in series if b.close_time < as_of]
       # ... aucun accès à des bars ≥ as_of
   ```

2. **Test "shift invariance"** : dans la suite pytest, on vérifie que
   décaler la série de N bars dans le futur ne change **rien** au signal
   calculé sur la fenêtre passée. Si ça change → fuite détectée.

3. **Cas spécifique** : les **stop-loss / take-profit** ne doivent jamais
   être touchés par le close du bar courant. On utilise High/Low du bar
   suivant le signal.

4. **Backtest harness checker** : `core/backtest.py` exécute un
   `_assert_no_lookahead()` au début de chaque run qui :
   - prend une série, masque les 30 derniers bars
   - calcule le signal final
   - démasque, recalcule
   - assert : décisions identiques → ✅

**Critère mesurable** : `pytest tests/test_no_lookahead.py` vert sur
**100 % des modules** qui consomment des séries temporelles.

---

### D2 — Survivorship bias

**Règle** : pour un backtest qui démarre le 2024-01-01, l'univers de
coins est **celui qui existait à cette date**, pas celui d'aujourd'hui.

**Mise en œuvre** :

1. **Snapshot d'univers** : table `coin_universe_snapshots(date, symbols)`
   avec une entrée par mois minimum.
2. **API backtest** : `run_backtest(start, end, universe=universe_at(start))`.
3. **Refus du backtest** si l'univers passé n'est pas disponible (pas de
   reconstruction post-hoc).

**Critère mesurable** : tout backtest produit un header listant les N
coins de l'univers + leur date d'ajout.

---

### D3 — Bougies corrompues

**Détection** : `core/data_quality.py` (à créer) applique 5 tests à
chaque bougie reçue :

| Test | Condition de rejet |
|---|---|
| Volume nul + range non nul | suspicieux, flag `flat_volume` |
| High < Low | corruption garantie, **rejet dur** |
| Close hors [Low, High] | corruption garantie, **rejet dur** |
| Range > 50× ATR_30 | spike anormal, flag `outlier_range` |
| Δt avec bar précédent ≠ timeframe attendu | série désalignée, flag `time_gap` |

**Politique** : flags warning → continuer mais logger ; rejet dur →
abandonner le cycle, retry suivant.

**Critère mesurable** : audit log contient ≥ 1 événement
`bar_quality_warning` par mois (preuve que la détection tourne et
n'est pas zombie).

---

### D4 — Bougies manquantes

**Politique** : aucune interpolation silencieuse.

**Mise en œuvre** :

1. À la réception d'une série de N bars, on vérifie que `len(series)`
   correspond à `(end - start) / timeframe`.
2. Si manquantes :
   - **< 5 % de la série** : interpolation linéaire **avec flag**
     `data_quality: interpolated_X_bars` joint au signal résultant.
   - **≥ 5 % de la série** : **rejet du cycle**, attente du suivant.
3. Le flag est propagé dans `audit_log` et empêche tout vote ensemble
   strong.

**Critère mesurable** : 0 cycle sans `data_quality` field rempli en
audit (même valeur "ok" doit être présente).

---

### D5 — Timezone mismatch

**Règle** : tout timestamp dans le code, la DB, les logs, les
notifications est en **UTC**. Conversion en locale uniquement à
l'affichage UI final.

**Mise en œuvre** :

1. SQLite : tous les `executed_at`, `closed_at` stockés en
   `datetime.utcnow().isoformat() + "Z"`.
2. Linter de code (à ajouter) : ban de `datetime.now()` sans
   `timezone.utc`, ban de `datetime.fromtimestamp()` sans `, tz=UTC`.
3. Tests pytest : un test global `test_no_naive_datetime.py` qui scanne
   le code source pour les patterns interdits.

**Critère mesurable** : test pytest vert.

---

### D6 — Data revision (Binance corrige a posteriori)

**Réalité** : très rare en spot mais possible (correction de bougie
suite à un rollback exchange).

**Politique** : pour les décisions de trading **live**, on prend la
donnée à T comme référence définitive. Pour les **backtests
reproductibles**, on snapshote la donnée :

1. `core/data_snapshot.py` (à créer) : à chaque téléchargement OHLCV,
   on sauvegarde dans `data/snapshots/<symbol>_<date>_<hash>.jsonl`.
2. Re-run de backtest = re-charge le snapshot, pas re-fetch Binance.
3. Hash SHA-256 du snapshot loggé dans le rapport de backtest pour
   prouver que deux runs ont utilisé la **même donnée bit-à-bit**.

**Critère mesurable** : 2 runs successifs du même backtest → résultats
identiques au cent près.

---

## 4. Reproductibilité / déterminisme

Au-delà de la donnée, les décisions doivent être reproductibles :

1. **Seeds aléatoires fixés** par cycle : `random.seed(cycle_id)`,
   loggué.
2. **Pas de `dict` non-ordonné** dans les structures qui sortent un
   ranking (Python 3.7+ : OK, mais on documente).
3. **Pas de `set()` dans les chemins de décision** (ordre indéterminé).
4. **Tests pytest** avec assertion de reproductibilité : même seed,
   mêmes données → mêmes trades.

**Critère mesurable** : `python run_backtest.py --seed 42` produit un
fichier de sortie dont le hash est constant entre 2 runs.

---

## 5. Audit trail des données

Chaque cycle doit produire dans `audit_log` un événement
`data_ingestion_completed` avec :

```json
{
  "cycle_id": "cycle_2026-04-25T10:00:00Z",
  "symbols_requested": ["BTCUSDT", "ETHUSDT", ...],
  "symbols_received": [...],
  "symbols_rejected": [],
  "bar_quality": {
    "BTCUSDT": "ok",
    "ETHUSDT": "interpolated_2_bars"
  },
  "data_snapshot_hash": "sha256:..."
}
```

→ Si un trade tourne mal, on peut **rejouer exactement le même cycle**
sur la **même donnée** (clé pour le post-mortem).

---

## 6. Politique de rejet en cascade

```
┌─ Bougie reçue
│
├─ D3 corruption dure ? ────────► REJET CYCLE
│
├─ D4 trous > 5 % ? ────────────► REJET CYCLE
│
├─ D3 flag warning ? ───────────► CONTINUER, mais
│                                    ensemble vote bloqué (pas de
│                                    nouvelle entrée, exits OK)
│
├─ D4 trous < 5 % ? ────────────► CONTINUER avec interpolation
│                                    flag, position sizing réduit -25%
│
└─ Tout OK ────────────────────► CONTINUER normal
```

**Principe** : le doute profite **toujours** à la prudence.

---

## 7. Critères de mesure (D1-D6)

À ajouter aux critères de terminaison (document 06) :

| # | Critère | Validation |
|:-:|---|---|
| D1 | Test no-lookahead vert sur 100 % des modules signal | pytest |
| D2 | Backtest produit un header avec snapshot d'univers | inspection |
| D3 | ≥ 1 événement `bar_quality_warning` / mois en audit | audit query |
| D4 | 0 cycle sans flag `data_quality` rempli | audit query |
| D5 | Test no-naive-datetime vert | pytest |
| D6 | 2 runs identiques → hash de sortie identique | scripted check |

---

## 8. Anti-pattern : ce qu'on ne fera jamais

- ❌ Fetch direct dans une fonction d'analyse (couplage signal/IO)
- ❌ Cache global muté par les fetchers (ordre indéterminé)
- ❌ Bougies « live » mélangées à des bougies fermées (mid-bar bias)
- ❌ Interpolation par moyenne sans flag (silent corruption)
- ❌ "On corrigera plus tard" → réécriture historique = bias

---

*v1.0 — 2026-04-25*
