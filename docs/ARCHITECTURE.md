# Architecture Technique — MstreamTrader

## Vue d'ensemble

MstreamTrader est construit en **couches séparées** avec un bus de données central (SQLite en mode WAL). Chaque module a une responsabilité unique, ne dépend des autres que via interfaces claires, et peut être testé isolément.

**20 modules Python**, **8903 lignes**, aucune dépendance externe lourde (pas NumPy, pandas, scipy, ni cryptography).

---

## Diagramme d'ensemble

```
┌─────────────────────────────────────────────────────────────────────┐
│                         COUCHE UI (Kivy)                            │
│  DashboardScreen  SignalsScreen  PortfolioScreen  SettingsScreen    │
│         │               │              │                │           │
│         └───────────────┴──────┬───────┴────────────────┘           │
│                    Clock.schedule_interval (30s / 35s)              │
└──────────────────────────────┬──────────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    MOTEUR DE DONNÉES (core/)                        │
│                                                                     │
│  market_data.py ──► indicators.py ──► signals.py                    │
│     (8 coins)         (RSI/MACD/...)    (scoring)                   │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                ┌───────────────┼───────────────┐
                ▼               ▼               ▼
┌───────────────────┐  ┌───────────────┐  ┌────────────────────────┐
│ DATABASE (SQLite) │  │  BOT MAÎTRE   │  │ EXCHANGE (optionnel)   │
│  9 tables, WAL    │◄►│  (daemon 60m) │◄►│ Binance REST v3 + SGL  │
│ + audit + ckpt    │  │               │  │ + Precisions dynamiques│
└───────────────────┘  └───────┬───────┘  └────────────────────────┘
                               │
         ┌─────────────────────┼─────────────────────────┐
         ▼                     ▼                         ▼
┌────────────────┐  ┌─────────────────────┐  ┌──────────────────────┐
│ CIRCUIT BREAKER│  │ INSTITUTIONAL CORE  │  │  AUDIT + HEALTH      │
│ 4 niveaux kill │  │ Kelly / Correlation │  │  Traçabilité pro     │
│ auto-recovery  │  │ MTF / Ensemble      │  │  Stall detection     │
└────────────────┘  │ Regime + Transition │  └──────────────────────┘
                    └─────────────────────┘
```

---

## Couche 1 — Données Marché (`core/market_data.py`)

**Responsabilité** : Récupérer les données brutes depuis **Binance public** (prioritaire) et **CoinGecko** (fallback).

### Fonctions principales

| Fonction | Description | Usage |
|---|---|---|
| `get_prices(coin_ids)` | Prix spot CoinGecko | Dashboard 30s |
| `get_historical_prices(id, days)` | CoinGecko OHLC (4h granularity) | Fallback |
| `get_binance_klines_public(id, interval, limit)` | Binance public klines (jusqu'à 1000 bougies) | Backtest + MTF |
| `get_ohlcv_for_analysis(id, days, interval)` | Source unifiée (Binance puis CoinGecko) | Bot Maître |
| `format_price(v)`, `format_large_number(v)` | Formatage UI | UI |

### Constantes

- `DEFAULT_COINS` : 8 coins (BTC, ETH, BNB, SOL, XRP, ADA, DOGE, DOT)
- `_COIN_ID_TO_BINANCE` : mapping CoinGecko id → Binance symbol

### Granularités supportées
| Interval | Seconds | Usage typique |
|---|---|---|
| 1m–30m | 60–1800 | Scalping (non utilisé actuellement) |
| 1h | 3600 | **Backtest principal + MTF court terme** |
| 4h | 14400 | CoinGecko default + MTF moyen |
| 1d | 86400 | **Regime detection + MTF long terme** |

---

## Couche 2 — Indicateurs Techniques (`core/indicators.py`)

**Pure Python, aucune dépendance.** Conservation indispensable pour Buildozer.

| Fonction | Retour | Fenêtre par défaut |
|---|---|---|
| `rsi(closes, period)` | list | 14 |
| `macd(closes, fast, slow, signal)` | {macd, signal, histogram} | 12/26/9 |
| `bollinger_bands(closes, period, std_dev)` | {upper, middle, lower, bandwidth} | 20, 2σ |
| `atr(highs, lows, closes, period)` | list | 14 |
| `stochastic(highs, lows, closes, k, d)` | {k, d} | 14/3 |
| `ema(closes, period)`, `sma(closes, period)` | list | — |
| `support_resistance(closes, window)` | {supports, resistances} | 10 |
| `compute_all(candles)` | dict complet avec last values | — |

---

## Couche 3 — Moteur de Signaux (`core/signals.py`)

**Responsabilité** : Transformer les indicateurs en `TradeSignal` actionnable.

### Pipeline de scoring

```
indicators dict
      │
      ├── _score_rsi         → ±40
      ├── _score_macd        → ±25
      ├── _score_bollinger   → ±25 × 0.85
      ├── _score_stochastic  → ±20 × 0.75
      └── _score_ema         → ±25 × 0.75
            │
            ▼
      total_score clampé [-100, +100]
            │
            ├─ ≥ 50  → STRONG_BUY
            ├─ ≥ 20  → BUY
            ├─ ≤ -50 → STRONG_SELL
            ├─ ≤ -20 → SELL
            └─ else  → HOLD
            │
            ▼
      confidence = min(100, |score| × 1.2)
            │
            ▼
      _compute_stop_take(price, signal, atr, supports, resistances)
      → SL (price − 1.5×ATR), TP (price + 3×ATR), R/R
            │
            ▼
      TradeSignal(coin_id, symbol, signal, score, confidence,
                  price, reasons, SL, TP, R/R, timestamp)
```

---

## Couche 4 — Base de Données (`core/database.py`)

**SQLite 9 tables, mode WAL** (thread-safe concurrent).

### Schéma

```sql
-- Configuration clé/valeur (+ API keys chiffrées)
settings (key TEXT PK, value TEXT)

-- Positions manuelles
portfolio (id, coin_id, symbol, quantity, avg_buy, created_at)

-- Ledger complet des trades
trades (id, coin_id, symbol, side, quantity, price, total_usdt,
        fee, source, note, exchange_id, executed_at)

-- Historique des signaux
signals_log (id, coin_id, symbol, signal, score, confidence, price,
             stop_loss, take_profit, risk_reward, reasons, logged_at)

-- Alertes utilisateur
price_alerts (id, coin_id, symbol, condition, target, triggered, created_at)

-- Positions auto ouvertes
open_positions (id, portfolio_type, coin_id, symbol,
                entry_price, quantity, stop_loss, take_profit,
                entry_usdt, status, opened_at, closed_at)

-- Journal décisions bot
auto_trader_log (id, portfolio_type, action, coin_id, symbol,
                 price, quantity, reason, logged_at)

-- [NOUVEAU] Audit Trail structuré
audit_log (id, event_type, coin_id, symbol, decision, severity,
           inputs_json, outputs_json, reasoning, cycle_id, created_at)

-- [NOUVEAU] Snapshots état volatile
bot_checkpoints (id, snapshot_json, created_at)
```

### Fonctions critiques

| Fonction | Thread-safe | Note |
|---|---|---|
| `get_setting(key)` / `set_setting(key, val)` | Via WAL | — |
| `get_setting_encrypted(key)` / `set_setting_encrypted(key, val)` | Oui | PBKDF2+XOR |
| `increment_numeric_setting(key, delta)` | **Atomique** | `BEGIN IMMEDIATE` + retry 5× backoff exp |
| `update_position_sl(pos_id, new_sl)` | Oui | Trailing SL |
| `record_trade(...)` + `update_position(...)` | Oui | — |

### Sources d'audit (champ `trades.source`)

| Source | Description |
|---|---|
| `MANUAL` | Trade via UI (TradeDialog) |
| `MANUAL_NO_EXCHANGE` | Manuel mode simu |
| `AUTO_ENTRY_MASTER` | Bot Maître achat |
| `AUTO_EXIT_TP_MASTER` | Bot Maître Take-Profit |
| `AUTO_EXIT_SL_MASTER` | Bot Maître Stop-Loss |
| `AUTO_ENTRY_SECURITE` / `AUTO_EXIT_*_SECURITE` | Legacy portefeuille Sécurité |
| `AUTO_ENTRY_LIBRE` / `AUTO_EXIT_*_LIBRE` | Legacy portefeuille Libre |
| `AUTO_SIGNAL` | Via execute_signal_trade (TradeDialog + Binance) |

---

## Couche 5 — Sécurité (`core/crypto.py`)

**PBKDF2-SHA256 (100 000 itérations)** + **XOR stream cipher** + salt séparé.

- Salt de 32 octets aléatoires généré au premier lancement, stocké dans `.mstream_salt` (permissions 0o600 sur POSIX).
- Préfixe `enc:` pour distinguer valeurs chiffrées et héritées en clair.
- Migration automatique au démarrage (`init_db()` chiffre les clés détectées en clair).

**Limites** : obfuscation renforcée, pas de crypto E2E. Un attaquant avec accès simultané au code + DB + salt peut déchiffrer. Pour usage mobile local, largement suffisant si permissions système respectées.

---

## Couche 6 — Exchange (`core/exchange.py`)

**Client Binance REST v3** avec **singleton caching** et **précisions dynamiques**.

### Singleton

`get_client()` retourne un client mis en cache (`_client_cache`). Invalidation via `invalidate_client_cache()` (appelée automatiquement lors du changement de clés dans Settings).

**Pourquoi** : recréer le client à chaque appel ferait recharger `/api/v3/exchangeInfo` (pour les précisions LOT_SIZE/PRICE_FILTER) à chaque ordre → rate limit + latence inutile.

### Précisions dynamiques

`_load_symbol_info(symbol)` fetche les filtres Binance (LOT_SIZE, PRICE_FILTER, MIN_NOTIONAL) via `/api/v3/exchangeInfo`, cache par symbole. Fallback sur table hardcodée si l'API échoue.

### Ordres disponibles

| Méthode | Type Binance | Usage |
|---|---|---|
| `place_market_order(sym, side, qty)` | MARKET | Entrée/Sortie simple |
| `place_market_order_usdt(sym, side, quote_qty)` | MARKET (quoteOrderQty) | **Utilisé par le bot** |
| `place_stop_loss_market(sym, side, qty, stop)` | **STOP_LOSS** | **Gap-safe**, recommandé |
| `place_stop_limit_order(...)` | STOP_LOSS_LIMIT | ⚠ Déconseillé, peut non-exécuter en gap |
| `place_limit_order(...)` | LIMIT | Entrées conditionnelles |

---

## Couche 7 — Bot Maître (`core/auto_trader.py`)

Voir [BOT_MAITRE.md](BOT_MAITRE.md) pour la doc métier. Ici, le résumé technique :

**Singleton** via `get_auto_trader()`. **Thread daemon** "BotMaitre" lancé au `start()`. Cycle toutes les **3600 s (60 min)** via `_stop_event.wait(CYCLE_INTERVAL)`.

Au démarrage : `auto_recover_on_startup()` restaure le dernier snapshot si < 24h.

### États de cycle (`_cycle_count` incrémenté à chaque passage)

| Fréquence | Action |
|---|---|
| Chaque cycle | Fetch données, run_periodic_tasks, run_master_cycle |
| `% health_check_every_n_cycles = 1` | Health check complet |
| `% checkpoint_every_n_cycles = 6` | Snapshot state volatile |
| `% audit_purge_every_n_cycles = 24` | Purge audit > 30 jours |
| TTL 6h (pas basé sur cycle_count) | Refresh régime + transition |

---

## Couche 8 — Institutional Grade (8 modules)

Chaque module a sa doc dédiée dans [INSTITUTIONAL.md](INSTITUTIONAL.md). Résumé ici :

| Module | Lignes | Rôle | Intégré via |
|---|---:|---|---|
| `circuit_breaker.py` | 311 | Kill switch 4 niveaux + auto-recovery | `get_circuit_breaker()` partout |
| `audit.py` | 376 | Audit trail JSON avec 15 types events | `audit.log_*()` partout |
| `health.py` | 215 | Health checks APIs + sanity prix | `_run_periodic_tasks` |
| `checkpoint.py` | 197 | Snapshot état volatile + recovery | `start()` + `_run_periodic_tasks` |
| `position_sizing.py` | 330 | Kelly Fractional + Volatility Targeting | `_look_for_master_entries_advanced` |
| `correlation.py` | 211 | Pearson correlation matrix rolling | `_look_for_master_entries_advanced` |
| `mtf.py` | 226 | Multi-TF Confluence 1h+4h+1d | `_compute_mtf()` |
| `ensemble.py` | 355 | 3 stratégies votent avec weighting par régime | `_compute_ensemble_vote()` |

---

## Couche 9 — Backtesting (`core/backtest.py` + `walk_forward.py` + `metrics.py`)

### Backtest Engine (`backtest.py`, 545 lignes)

Simule le comportement du Bot Maître sur historique :
- Timestamps alignés par intersection entre coins
- Warmup 60 bougies (stabilisation indicateurs)
- Check exits intra-candle (SL via low, TP via high, **SL avant TP** = pessimisme)
- Régime détecté à chaque bougie (si `use_regime_filter=True`)
- Trailing SL via ATR implicite
- Slippage et fees modélisés

### Walk-Forward (`walk_forward.py`, 211 lignes)

Valide hors-sample via fenêtres glissantes :
- `window_days` (60 par défaut), `step_days` (30)
- Train/Test split via `train_ratio` (70/30)
- Agrégation : avg_return, avg_sharpe, avg_pf, consistency
- Robustesse : consistency > 60 % + avg Sharpe > 0.5 + avg PF > 1.2

### Metrics (`metrics.py`, 323 lignes)

Fonctions pure Python :
- `total_return_pct`, `annualized_return_pct`, `max_drawdown_pct`
- `sharpe_ratio`, `sortino_ratio`, `calmar_ratio` — annualisables
- `profit_factor`, `expectancy`, `win_rate_pct`, `avg_win_loss`
- `r_multiple_stats` (avg, median, best, worst)
- `compute_full_report()` / `format_report()` — rapport consolidé

---

## Couche 10 — UI (`screens/` + `kv/`)

**Aucune logique métier.** Les écrans sont des consommateurs de données.

### Refresh pattern

| Écran | Refresh | Thread-safety |
|---|---|---|
| Dashboard | 30 s (`Clock.schedule_interval`) | **`threading.Lock` non-bloquant** pour anti-spam |
| Signaux | 35 s (via `App._sync_screens`) | Kivy Clock main thread |
| Portfolio | 35 s + `on_enter` | Idem |
| Settings | `on_enter` uniquement | Idem |

### Dashboard anti-spam threads

Si `_refresh` est rappelé pendant qu'un fetch HTTP est en cours (CoinGecko lent), le nouveau thread est **skippé** grâce à `threading.Lock.acquire(blocking=False)`. Évite la multiplication des fetches parallèles et le hit du rate limit.

---

## Flux de données end-to-end

```
┌─────────────────────────────────────────────────────────────────────┐
│  TOUS LES 30 S  (DashboardScreen._fetch_data, UI thread pool)       │
├─────────────────────────────────────────────────────────────────────┤
│  CoinGecko → get_prices()              → 1 HTTP call                │
│  CoinGecko → get_historical_prices()   × 8 coins → 8 HTTP calls     │
│                ↓                                                    │
│  indicators.compute_all()              × 8 coins                    │
│                ↓                                                    │
│  signals.analyze(cid, sym, indics)     × 8 coins                    │
│                ↓                                                    │
│  database.log_signal()                 × 8 (INSERT signals_log)     │
│                ↓                                                    │
│  self._prices / self._signals mis à jour                            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│  TOUS LES 35 S  (MstreamTraderApp._sync_screens, main thread)       │
├─────────────────────────────────────────────────────────────────────┤
│  signals_screen.refresh(signals)       [UI update]                  │
│  portfolio_screen.refresh(prices)      [UI update]                  │
│  auto_trader.update_market_data(p, s)  [_data_timestamp update]     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│  TOUS LES 60 MIN  (AutoTrader._cycle, daemon thread)                │
├─────────────────────────────────────────────────────────────────────┤
│  1. _cycle_count++, check data_age > 65 min → fetch autonome        │
│  2. _run_periodic_tasks :                                           │
│     - health check (cycle%1)                                        │
│     - checkpoint save (cycle%6)                                     │
│     - audit purge (cycle%24)                                        │
│  3. _run_master_cycle :                                             │
│     a. _refresh_regime_if_stale (TTL 6h) → détecte transition       │
│     b. circuit_breaker.report_capital(total_equity)                 │
│     c. _update_trailing_stops(prices, signals)                      │
│     d. _manage_master_exits → audit + circuit_breaker.report_trade  │
│     e. _look_for_master_entries_advanced :                          │
│        - profile régime (+blend transition si score > 0.5)          │
│        - filtre base (score/conf/RR)                                │
│        - ensemble vote                                              │
│        - correlation block                                          │
│        - MTF confluence                                             │
│        - Kelly sizing (cold start si is_defaults)                   │
│        - _execute_entry → audit + DB                                │
│     f. log_cycle_completed                                          │
│  4. Legacy portfolios (securite/libre) si actifs                    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Contraintes techniques

### Compatibilité Android (Buildozer)

| Contrainte | Raison |
|---|---|
| Pure Python pour indicateurs, metrics, crypto, correlation | Buildozer ne peut compiler NumPy/pandas/cryptography sans recipes avancées |
| `urllib` stdlib pour HTTP dans `core/` | `requests` disponible mais `urllib` plus sûr sur Android |
| Imports paresseux dans méthodes | Évite crashes import-time sur Android |
| Pas de multiprocessing | Non supporté correctement par Kivy/Android |

### Thread Safety

| Règle | Mécanisme |
|---|---|
| UI uniquement thread main | `Clock.schedule_once(lambda dt: ..., 0)` |
| Données partagées bot | `threading.Lock()` sur `_latest_prices`/`_latest_signals` |
| SQLite concurrent | WAL mode + connexion par appel + `BEGIN IMMEDIATE` pour writes atomiques |
| Circuit breaker state | `threading.Lock()` sur toutes mutations |
| Dashboard anti-spam | `threading.Lock(non-blocking)` dans `_refresh` |

### Performance mobile

| Optimisation | Valeur |
|---|---|
| Dashboard refresh | 30 s (rate limit CoinGecko) |
| Bot cycle | 60 min (aligné granularité 1h) |
| Startup delay | 45 s |
| Data stale threshold | 65 min (> 1 cycle) |
| Binance client cache | Singleton, invalidé sur change clés |
| Audit purge auto | 30 j par défaut, configurable |
