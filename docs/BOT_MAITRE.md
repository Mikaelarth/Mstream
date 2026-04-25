# Bot Maître — Documentation Complète

## Qu'est-ce que le Bot Maître ?

Moteur de trading algorithmique autonome. **Composant central de MstreamTrader**, il dispose d'un budget dédié, prend toutes les décisions de trading sans intervention humaine, et fait croître ce capital par réinvestissement systématique des profits.

Le bot est **régime-aware**, **circuit-protégé**, **Kelly-dimensionné**, **corrélation-filtré**, **MTF-confirmé**, **ensemble-voté**, **audité**, **health-checké** et **checkpointé**. Soit les 10 techniques du niveau institutional grade ([voir INSTITUTIONAL.md](INSTITUTIONAL.md)).

L'utilisateur n'a qu'**un seul rôle** : définir le capital initial et activer le bot dans Configuration.

---

## Cycle de décision du Bot Maître

Cycle toutes les **60 minutes** (`CYCLE_INTERVAL = 3600`).

```
┌─────────────────────────────────────────────────────────────────┐
│  1. cycle_count++                                               │
│     Génération d'un cycle_id unique (audit grouping)            │
├─────────────────────────────────────────────────────────────────┤
│  2. Données marché                                              │
│     Si âge < 65 min → utilisation des données injectées         │
│     Sinon → fetch autonome (Binance+CoinGecko)                  │
├─────────────────────────────────────────────────────────────────┤
│  3. Tâches périodiques                                          │
│     - Health check (chaque cycle)                               │
│     - Checkpoint snapshot (tous les 6 cycles = 6h)              │
│     - Audit purge (tous les 24 cycles = 1×/jour)                │
├─────────────────────────────────────────────────────────────────┤
│  4. Régime : refresh si TTL 6h expiré                           │
│     - detect_regime() → BULL/BEAR/NEUTRAL                       │
│     - detect_regime_transition() → early signal                 │
│     - Log audit si changement                                   │
├─────────────────────────────────────────────────────────────────┤
│  5. Circuit Breaker                                             │
│     - report_capital(total_equity) → détecte drawdown           │
│     - auto_recover_check() → WARNING→HEALTHY, TRIGGERED→WARNING │
│     - Si FROZEN : STOP (pas même les exits)                     │
├─────────────────────────────────────────────────────────────────┤
│  6. Trailing Stop-Loss                                          │
│     Si gain > 1.5 % de l'entrée :                               │
│     - SL adaptatif ATR (1.5 × ATR estimé)                       │
│     - Fallback 2.5 % si ATR indisponible                        │
│     - SL ne descend JAMAIS (verrouillage des gains)             │
├─────────────────────────────────────────────────────────────────┤
│  7. Gestion des sorties                                         │
│     Pour chaque position ouverte :                              │
│     - Si prix <= stop_loss → EXIT_SL (vente market)             │
│     - Si prix >= take_profit → EXIT_TP (vente market)           │
│     - Mise à jour budget via increment_numeric_setting atomique │
│     - Audit log + circuit_breaker.report_trade_result           │
├─────────────────────────────────────────────────────────────────┤
│  8. Recherche d'entrées (si Circuit HEALTHY/WARNING)            │
│     8a. Profil du régime (avec blending transition si ≥ 0.5)    │
│     8b. Matrice corrélation (refresh si utilisée)               │
│     8c. Stats historiques (pour Kelly)                          │
│     8d. Pour chaque coin candidat :                             │
│         - Filtre signal (score/conf/R/R selon profil)           │
│         - Ensemble vote (3 stratégies)                          │
│         - Correlation block (refus si > 0.75 avec positions)    │
│         - MTF Confluence (1h+4h+1d alignés)                     │
│     8e. Kelly sizing (ou cold start si < 10 trades)             │
│     8f. Exécution ordre + audit trail complet                   │
├─────────────────────────────────────────────────────────────────┤
│  9. Legacy portfolios (Sécurité/Libre) si activés               │
├─────────────────────────────────────────────────────────────────┤
│  10. log_cycle_completed (résumé dans audit_log)                │
└─────────────────────────────────────────────────────────────────┘
```

---

## Profils adaptatifs par régime

Les paramètres du bot **ne sont pas fixes**. Ils s'adaptent au régime BTC détecté via EMA 200 daily :

| Paramètre | 🟢 BULL | 🟡 NEUTRAL | 🔴 BEAR |
|---|---:|---:|---:|
| Score minimum | 55 | 60 | **70** |
| Confiance minimum | 65 % | 70 % | **75 %** |
| Ratio R/R minimum | 2.5 | 3.0 | **3.5** |
| Risque par trade | 5 % | 3.5 % | **2 %** |
| Max positions | 4 | 3 | **2** |
| Max capital investi | 80 % | 60 % | **40 %** |

**Blending transition** : si une bascule est détectée (score > 0.5), les paramètres sont **moyennés** entre régime courant et régime cible. Permet une adaptation progressive.

---

## Filtres successifs d'une entrée

Pour qu'un signal se transforme en trade, **TOUS** ces filtres doivent passer :

```
TradeSignal du coin X
      │
      ├─ Filtre 1 : STRONG_BUY uniquement
      ├─ Filtre 2 : score >= profil.min_score
      ├─ Filtre 3 : confiance >= profil.min_confidence  
      ├─ Filtre 4 : R/R >= profil.min_rr
      ├─ Filtre 5 : coin_id NOT IN already_holds
      ├─ Filtre 6 : cooldown (6h) NOT actif
      ├─ Filtre 7 : Ensemble vote >= 2/3 stratégies d'accord
      ├─ Filtre 8 : Correlation < 0.75 avec positions ouvertes
      ├─ Filtre 9 : MTF Confluence >= 2/3 timeframes bullish
      │          ET TF long-terme NOT bearish fort
      └─► Candidat validé
              │
              ├─ Sizing Kelly (ou cold start si is_defaults)
              ├─ Vérif disponibilité capital
              └─► _execute_entry
```

**Chaque refus** est loggué dans `audit_log` avec la raison précise. Traçabilité totale.

---

## Stop-Loss Trailing ATR

Le bot ne se contente pas d'un SL fixe. Dès qu'une position gagne plus de **1.5 %**, le SL remonte automatiquement.

### Algorithme adaptatif

```
Pour chaque position ouverte :
  gain_pct = (prix_actuel - entry_price) / entry_price × 100
  
  if gain_pct >= 1.5 :
    # Estimer ATR actuel via signal récent : atr ≈ (price − SL_suggéré) / 1.5
    if sig_actuel.stop_loss dispo :
      atr_est = |sig.price − sig.stop_loss| / 1.5
      new_sl = price − (1.5 × atr_est)      # ATR-adaptatif
    else :
      new_sl = price × (1 − 2.5 / 100)      # Fallback %
    
    if new_sl > sl_actuel :                 # Jamais descendre
      update_position_sl(pos_id, new_sl)
```

### Exemple concret

```
Achat BTC @ $40 000, SL initial = $38 000 (−5% ATR)

Cycle 1 : prix = $40 800 (+2%)
  gain_pct (2.0%) > trigger (1.5%) → on recalcule
  ATR_est ≈ $400 (volatilité actuelle)
  new_sl = $40 800 − (1.5 × $400) = $40 200
  → SL remonté de $38 000 à $40 200 (verrouille $200 de gain)

Cycle 2 : prix = $42 000 (+5%)
  new_sl = $42 000 − (1.5 × $400) = $41 400
  → SL remonté à $41 400 (verrouille $1 400 de gain)

Cycle 3 : prix = $41 000 (repli)
  prix ($41 000) < SL ($41 400) → EXIT_SL
  Profit réalisé = (41 000 − 40 000) × qty − fees
  (Sans trailing, le SL initial à $38 000 n'aurait pas protégé ce gain)
```

---

## Position Sizing avec Kelly

Le dimensionnement des positions utilise le **Kelly Criterion Fractional** (1/4 Kelly), combiné avec **Volatility Targeting** et un plafond de sécurité.

### Mode Cold Start (protection critique)

Quand le bot démarre et n'a PAS encore 10 trades historiques, `compute_historical_stats()` retourne `is_defaults=True` avec des valeurs **fictives** (WR 45 %, R/R 2:1). Utiliser Kelly sur ces valeurs serait dangereux.

**Solution intégrée** : le bot détecte `is_defaults` et bascule en mode **ultra-conservateur** :
- Taille position = **min(1 % du budget, $50)**
- Pas de calcul Kelly
- Logging explicite : `"Cold start — N/10 trades reels"`

### Mode normal (≥ 10 trades historiques)

```
stats_hist = (win_rate, avg_win, avg_loss)  ← depuis open_positions joined avec trades

sizing = optimal_position_size(
    capital          = budget_master,
    win_rate, avg_win, avg_loss,   ← réels
    entry_price      = sig.price,
    stop_loss        = sig.stop_loss,
    realized_vol_pct = ATR / price,
    max_risk_per_trade = 2.0,       ← HARD CAP (2% max à risquer)
    max_position_pct   = 25.0,      ← plafond par position
    kelly_fraction_used = 0.25,     ← 1/4 Kelly
    vol_target_pct     = 2.0,
)
→ retourne le MIN de 4 contraintes (Kelly, Vol-adjusted, max_risk, max_position)
```

**Exemple** : capital $1000, WR 55 %, R/R 2:1, SL à −5 % du prix, ATR = 2.5 %
- Kelly fractional = 1/4 × ((0.55 × 2 − 0.45) / 2) = 8.1 %
- Kelly size = $81.25
- max_risk = 2 % × $1000 / 5 % = $400
- vol_multiplier = 2.0 / 2.5 = 0.8
- binding = **Kelly** → $81.25 investi (risk réel = $4.06 = 0.41 %)

---

## Protection du Capital

### Limite d'exposition simultanée
80 % max du budget investi simultanément (en BULL), 60 % en NEUTRAL, 40 % en BEAR. Les 20-60 % restants constituent une réserve.

### Cooldown
Après chaque trade sur un coin, **6 heures** d'attente avant de retourner sur ce même coin. Évite les trades en cascade sur un coin en tendance baissière.

### Circuit Breaker (4 niveaux)

| État | Seuil déclenchement | Action |
|---|---|---|
| 🟢 HEALTHY | — | Fonctionnement normal |
| 🟡 WARNING | Anomalies mineures, perte anormale, health check fail | Audit renforcé, trading continue |
| 🔴 TRIGGERED | 5 SL consécutifs OU > 10 % DD en 4h OU > 20 % DD total OU > 8 SL/jour | **Entrées bloquées**, exits OK |
| ⛔ FROZEN | 5 erreurs API consécutives | **STOP TOTAL**, `manual_reset()` requis |

**Auto-recovery** : WARNING→HEALTHY après 2h, TRIGGERED→WARNING après 12h.

---

## Calcul du Stop-Loss / Take-Profit d'entrée

Au moment où le bot ouvre une position, le SL et TP viennent du `TradeSignal` calculé par `signals.analyze()` :

```
ATR = Average True Range (14 périodes)

Stop-Loss  = prix_entrée − (1.5 × ATR)
Take-Profit = prix_entrée + (3.0 × ATR)
Ratio R/R  = 3.0 / 1.5 = 2.0 minimum théorique

Ajustements :
  Stop-Loss  = max(SL_ATR, niveau_support_proche × 0.995)
  Take-Profit = min(TP_ATR, niveau_résistance_proche × 1.005)
```

Le R/R **réel** dépend des ajustements support/résistance. Le bot exige un R/R minimum selon le régime (2.5 en bull, 3.5 en bear).

---

## Fetch Autonome

Le bot ne dépend pas de l'UI. Si les données injectées par le dashboard ont plus de **65 minutes** de retard (app en arrière-plan, pas de connexion UI), le bot fetch ses propres données :

```python
# Pour chaque coin
prices   = market_data.get_prices()
candles  = market_data.get_ohlcv_for_analysis(cid, days=21, interval="1h")
indics   = indicators.compute_all(candles)
signal   = signals.analyze(cid, symbol, indics)
```

Garantit que le bot continue de trader même si l'application est minimisée sur Android.

---

## Configuration utilisateur

| Paramètre UI | Clé DB | Défaut | Description |
|---|---|---|---|
| Budget Bot Maître | `budget_master` | 0 | Capital courant (évolue avec P&L) |
| Capital initial | `budget_master_initial` | 0 | Référence ROI — ne change pas auto |
| Risque par trade | `risk_master` | 5.0 | Override user du risk_pct (profil écrasé) |
| Switch ON/OFF | `auto_trade_master` | false | Activation |

### Règles de modification

- **Budget** : mis à jour auto à chaque exit (profit ou perte). Modification manuelle entre cycles OK, mais évitez pendant positions ouvertes (fausse le sizing).
- **Capital initial** : n'est **jamais modifié auto** → référence stable pour le ROI. Utilise `reset_master_initial()` (bouton UI) pour repart le compteur.
- **Risque** : override l'adaptation automatique du régime. Si vide, c'est le profil régime qui décide.

---

## Journal des Actions

Trois tables logguent les actions :

### `auto_trader_log` (historique opérationnel simple)

| Action | Signification |
|---|---|
| `ENTRY` | Position ouverte |
| `EXIT_TP` | Position fermée sur Take-Profit |
| `EXIT_SL` | Position fermée sur Stop-Loss |
| `SKIP` | Signal éligible ignoré (raison dans `reason`) |
| `PAUSE` | Bot suspendu (drawdown, FROZEN) |
| `ERROR` | Erreur d'exécution |

Visible dans **Portfolio → Journal Auto-Trader**.

### `audit_log` (traçabilité institutional détaillée)

15 types d'événements avec JSON inputs/outputs complets. Voir [INSTITUTIONAL.md § Audit](INSTITUTIONAL.md).

### `trades` (ledger comptable)

Tous les trades exécutés (BUY/SELL) avec source, frais, exchange_id.

---

## KPIs du Bot Maître

| KPI | Formule | Où voir |
|---|---|---|
| ROI | (budget_actuel − budget_initial) / budget_initial × 100 | Portfolio + Status bar |
| Capital courant | `budget_master` | Partout |
| PnL non réalisé | Σ (prix_actuel − entry_price) × qty | Portfolio |
| Positions ouvertes | COUNT (status='OPEN') | Portfolio |
| Trades fermés | COUNT | Portfolio |
| Win Rate | wins / total × 100 | Portfolio |
| Sharpe annualisé | via metrics.py (backtest) | `run_backtest.py` |
| Profit Factor | Σ gains / Σ pertes | `run_backtest.py` |

---

## Modes de Fonctionnement

### Mode Paper Trading (sans Binance)
- Aucune clé API requise
- Ordres simulés au prix CoinGecko
- Tous les trades enregistrés en DB
- Circuit Breaker + Audit + Kelly fonctionnent normalement
- **Recommandé pour tester la stratégie au moins 2 semaines**

### Mode Réel (avec Binance)
- Clés API Binance chiffrées via `crypto.py` (PBKDF2)
- Ordres MARKET en temps réel
- STOP_LOSS market (pas LIMIT — gap-safe)
- Singleton client Binance + précisions dynamiques `/exchangeInfo`
- Slippage estimé sur petits volumes

---

## Ce que le bot ne fait PAS

- ❌ **Short selling** — uniquement long (achat → vente)
- ❌ **Trading sur contrats futurs** — spot Binance uniquement
- ❌ **Arbitrage inter-exchange** — mono-exchange
- ❌ **News / sentiment analysis** — technique pure
- ❌ **Trading haute fréquence** — cycle 1h, pas du scalping

---

## Limites connues

- **Cold start** : les 10 premiers trades utilisent un sizing ultra-prudent (1 % du budget). Le Kelly normal ne s'active qu'après accumulation d'un échantillon statistique.
- **Régime** : nécessite 200 jours d'historique BTC daily. Si un nouveau coin n'a pas cette profondeur, fallback NEUTRAL.
- **Corrélation** : calculée sur 10 jours par défaut. Peu fiable en période de changement de régime (corrélations deviennent instables).
- **Flash crashes** : le SL market exécute mais à un prix potentiellement éloigné du stop. ATR modère ce risque, pas de garantie absolue.
- **MTF** : ajoute 3 HTTP calls par candidat qualifié. En cas de saturation réseau, le check peut échouer et le signal passe par défaut (soft fail).
