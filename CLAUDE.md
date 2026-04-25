# MstreamTrader — Contexte Technique pour Claude Code

## Vue d'ensemble

Bot de trading crypto autonome de **niveau institutional grade** construit en Python/Kivy, ciblant Android via Buildozer. **20 modules Python, 8903 lignes**, zero dépendance externe pour le cœur (indicateurs, metrics, ensemble voting...).

Le Bot Maître est le composant central : moteur autonome qui gère son propre budget, orchestre 10 techniques algorithmiques pro, et fait croître son capital de façon entièrement automatique.

---

## Structure complète du projet

```
MstreamTrader/
├── main.py                      # App Kivy (318 l) — CoinListWidget, TradeDialog, sync
├── run_backtest.py              # CLI backtest (209 l)
├── optimize_params.py           # CLI grid search + walk-forward (398 l)
│
├── core/                        # 20 modules (~6 717 lignes)
│   ├── auto_trader.py           # (1118 l) Bot Maître — orchestration institutional
│   ├── database.py              # (661 l)  SQLite WAL, 9 tables, atomic increment
│   ├── backtest.py              # (545 l)  Moteur de simulation multi-coins
│   ├── exchange.py              # (502 l)  Binance API v3 + singleton + precisions dyn
│   ├── audit.py                 # (376 l)  Audit Trail structuré — 15 types events
│   ├── signals.py               # (369 l)  Scoring multi-indicateurs
│   ├── ensemble.py              # (355 l)  3 sous-stratégies votent
│   ├── position_sizing.py       # (330 l)  Kelly Fractional + Volatility Targeting
│   ├── metrics.py               # (323 l)  Sharpe/Sortino/Calmar/R-multiples
│   ├── indicators.py            # (313 l)  RSI/MACD/BB/ATR/Stoch/EMA — pure Python
│   ├── circuit_breaker.py       # (311 l)  Kill switch 4 niveaux + auto-recovery
│   ├── regime.py                # (309 l)  Bull/Bear/Neutral + transition detection
│   ├── market_data.py           # (230 l)  CoinGecko + Binance public klines
│   ├── mtf.py                   # (226 l)  Multi-Timeframe Confluence
│   ├── health.py                # (215 l)  Health checks continu (APIs, sanity)
│   ├── walk_forward.py          # (211 l)  Walk-Forward Analysis
│   ├── correlation.py           # (211 l)  Pearson dynamic correlation matrix
│   ├── checkpoint.py            # (197 l)  Snapshot + auto-recovery post-crash
│   ├── crypto.py                # (118 l)  PBKDF2+XOR pour chiffrer API keys
│   └── __init__.py
│
├── screens/                     # 4 écrans Kivy (~1 056 lignes)
│   ├── dashboard_screen.py      # (161 l)  Refresh 30s, thread-safe via lock
│   ├── portfolio_screen.py      # (359 l)  Bot Maître + positions + journal
│   ├── settings_screen.py       # (341 l)  API keys (chiffrées), budgets, switches
│   ├── signals_screen.py        # (195 l)  Liste des cartes signaux
│   └── __init__.py
│
├── kv/
│   ├── dashboard.kv             # Layout principal
│   ├── signals.kv
│   ├── portfolio.kv
│   └── settings.kv
│
├── docs/                        # 7 documents
│   ├── PROJECT_STATE.md         # État réel code vs doc
│   ├── ARCHITECTURE.md          # Architecture technique
│   ├── BOT_MAITRE.md            # Documentation du bot
│   ├── INSTITUTIONAL.md         # Les 10 techniques pro
│   ├── REGIME.md                # Filtre Bull/Bear
│   └── BACKTESTING.md           # Backtest + walk-forward
│
├── buildozer.spec               # Config Android (API 33, arm64)
├── mstream_trader.db            # SQLite (inclus en dev)
├── .mstream_salt                # Salt chiffrement (généré runtime, 0o600)
└── README.md
```

---

## Règles critiques de développement

### Compatibilité Android obligatoire
- **Zero dépendance lourde** : pas de NumPy, pandas, scipy, ni cryptography. Tous les calculs sont en pure Python.
- Seules dépendances : `kivy>=2.3.0`, `requests>=2.31.0`.
- **Imports paresseux** dans les méthodes (pas au top-level) pour éviter les crashes au démarrage Android.
- `urllib` (stdlib) pour les appels HTTP dans `core/`, pas `requests` directement.

### Thread safety (IMPÉRATIF)
- Le Bot Maître tourne dans un **thread daemon** séparé (`threading.Thread(daemon=True)`).
- Toutes les mises à jour UI depuis un thread background → `Clock.schedule_once(lambda dt: ..., 0)`.
- Le `_lock` dans `AutoTrader` protège `_latest_prices` et `_latest_signals`.
- Dashboard utilise `threading.Lock(non-blocking)` pour éviter les threads qui s'empilent (cf. [screens/dashboard_screen.py](MstreamTrader/screens/dashboard_screen.py)).
- **Ne jamais** modifier un widget Kivy depuis un thread non-main.

### Base de données
- Pattern `with get_connection() as conn:` à chaque appel (nouvelle connexion).
- **WAL mode** activé — safe pour concurrent thread/main.
- Requêtes **paramétrées** (jamais de f-string dans SQL — injection risk).
- `increment_numeric_setting(key, delta)` : atomique via `BEGIN IMMEDIATE` + **retry exponentiel** (5 tentatives) sur SQLITE_BUSY.

### Sécurité
- Clés API Binance **chiffrées** via [core/crypto.py](MstreamTrader/core/crypto.py) (PBKDF2-SHA256 100k itérations + XOR).
- Salt stocké dans `.mstream_salt` (hors DB), permission 0o600 sur POSIX.
- Préfixe `enc:` pour compat ascendante avec valeurs en clair.
- Migration automatique au `init_db()` si clés en clair détectées.
- Fonctions : `database.get_setting_encrypted(key)`, `database.set_setting_encrypted(key, value)`.

---

## Les 10 techniques Institutional Grade (toutes INTÉGRÉES)

| # | Technique | Module | Appelée depuis |
|---|---|---|---|
| 1 | Régime Bull/Bear/Neutral | `regime.detect_regime()` | `_refresh_regime_if_stale()` cycle 6h |
| 2 | Détection transition | `regime.detect_regime_transition()` | `_refresh_regime_if_stale()` |
| 3 | Kelly Criterion Fractional | `position_sizing.optimal_position_size()` | `_look_for_master_entries_advanced` |
| 4 | Dynamic Correlation Matrix | `correlation.compute_correlation_matrix()` | `_look_for_master_entries_advanced` |
| 5 | Ensemble Voting (3 stratégies) | `ensemble.vote()` | `_compute_ensemble_vote()` |
| 6 | Multi-Timeframe Confluence | `mtf.analyze_confluence()` | `_compute_mtf()` |
| 7 | Circuit Breaker 4 niveaux | `circuit_breaker.get_circuit_breaker()` | `_run_master_cycle` |
| 8 | Audit Trail | `audit.log_*()` | Partout (15 types d'events) |
| 9 | Health Checks | `health.get_health_checker()` | `_run_periodic_tasks` |
| 10 | Checkpointing | `checkpoint.save_snapshot()` + `auto_recover_on_startup()` | `_run_periodic_tasks` + `start()` |

**Bonus** : Walk-Forward (`walk_forward.run_walk_forward()`) utilisable via `optimize_params.py --walk-forward`.

---

## Composants clés

### AutoTrader (`core/auto_trader.py`)

Singleton via `get_auto_trader()`. 4 cycles périodiques en plus du cycle principal :

```python
# Toutes les 60 min (CYCLE_INTERVAL = 3600)
def _cycle(self):
    self._cycle_count += 1
    # Fetch data (injected or autonomous)
    # Run periodic tasks :
    #   - Health check (every 1 cycle)
    #   - Checkpoint save (every 6 cycles)
    #   - Audit purge (every 24 cycles)
    # Run master cycle :
    #   - Refresh regime + transition (every 6h TTL)
    #   - Report capital to circuit breaker
    #   - Trailing stops
    #   - Manage exits
    #   - Look for entries (advanced)
    # Run legacy portfolios
```

**MASTER_CONFIG** contient tous les switches (`use_ensemble`, `use_mtf_confluence`, `use_kelly_sizing`, `use_correlation_block`, `use_regime_transition`, ...).

### Database (`core/database.py`)

**9 tables** :
- `settings` — key/value (budgets, API keys chiffrées, flags)
- `portfolio` — positions manuelles
- `trades` — ledger complet (source: MANUAL, AUTO_ENTRY_MASTER, AUTO_EXIT_TP_MASTER, etc.)
- `signals_log` — historique des signaux
- `price_alerts` — alertes prix user
- `open_positions` — positions auto (portfolio_type: master, securite, libre)
- `auto_trader_log` — journal décisions bot
- `audit_log` — **nouveau** : audit trail structuré avec JSON inputs/outputs
- `bot_checkpoints` — **nouveau** : snapshots état volatile

Fonctions critiques :
- `increment_numeric_setting(key, delta)` — atomique avec retry
- `get_setting_encrypted(key)` / `set_setting_encrypted(key, value)`
- `update_position_sl(position_id, new_sl)` — trailing SL
- `get_auto_portfolio_summary(ptype, prices)` — PnL réalisé + non-réalisé

### Exchange (`core/exchange.py`)

**Singleton client Binance** (`_client_cache`) — invalidé via `invalidate_client_cache()` quand les clés changent. Évite de recréer le client à chaque ordre, cache les précisions dynamiques.

**Précisions depuis `/api/v3/exchangeInfo`** (pas hardcodé). Fallback sur une table si l'API échoue.

Méthodes clés :
- `place_market_order(symbol, side, qty)`
- `place_market_order_usdt(symbol, side, quote_qty)` — utilisé par le bot
- `place_stop_loss_market(symbol, side, qty, stop_price)` — **STOP_LOSS (pas LIMIT)**, gap-safe
- `place_stop_limit_order(...)` — déconseillé (risque non-exécution en gap)

### Position Sizing (`core/position_sizing.py`)

**Kelly Fractional** (1/4 Kelly) + **Volatility Targeting** + max_risk cap.

**Cold start protection** : si `compute_historical_stats()` retourne `is_defaults=True` (< 10 trades historiques), le bot force un sizing ultra-conservateur (1 % du budget, plafond $50) au lieu du Kelly fictif.

**Matching entry/exit** : via `open_positions.closed_at` avec tolérance 2 secondes (vs l'ancien matching par subquery `trades > executed_at` qui croisait les cycles).

### Circuit Breaker (`core/circuit_breaker.py`)

4 états : `HEALTHY` / `WARNING` / `TRIGGERED` / `FROZEN`. Auto-recovery timer (WARNING→HEALTHY après 2h, TRIGGERED→WARNING après 12h). FROZEN nécessite `manual_reset()`.

Déclencheurs :
- 5 SL consécutifs → TRIGGERED
- > 10 % DD en 4h → TRIGGERED
- > 20 % DD total (depuis peak) → TRIGGERED
- 5 erreurs API consécutives → FROZEN

### Audit (`core/audit.py`)

**15 types d'événements** persistés en JSON dans `audit_log` avec `cycle_id` unique pour grouper.

Helpers : `log_signal_analyzed`, `log_signal_qualified`, `log_signal_rejected`, `log_entry_executed`, `log_position_closed`, `log_regime_change`, `log_circuit_event`, `log_correlation_block`, `log_kelly_sizing`, `log_cycle_completed`.

Purge automatique tous les 24 cycles (1 fois/jour) : `purge_old_events(days=30)`.

### Ensemble Voting (`core/ensemble.py`)

3 stratégies votent avec **pondération par régime** :

| Stratégie | Bull | Neutral | Bear |
|---|---:|---:|---:|
| Trend Follower | 1.3× | 0.8× | 0.4× |
| Mean Reversion | 0.6× | 1.2× | 0.5× |
| Breakout Hunter | 1.0× | 1.0× | 0.6× |

Validation : `ensemble.is_ensemble_qualified(decision, min_agreement=2, min_score=30, min_confidence=50)`.

---

## Flux de données

```
[DashboardScreen._fetch_data] — toutes les 30s (UI)
    ↓
market_data.get_prices()           → prix spot
market_data.get_ohlcv_for_analysis() × 8 coins → bougies 1h
    ↓
indicators.compute_all()
    ↓
signals.analyze()  → TradeSignal
    ↓
database.log_signal() + self._prices, self._signals

[MstreamTraderApp._sync_screens] — toutes les 35s
    ↓
signals_screen.refresh()
portfolio_screen.refresh()
auto_trader.update_market_data(prices, signals)

[AutoTrader._run_loop] — thread daemon, cycle 60 min
    ↓
_cycle()
    ├─ Fetch autonome si data_age > 65 min
    ├─ _run_periodic_tasks (health / checkpoint / purge)
    ├─ _run_master_cycle :
    │     ├─ _refresh_regime_if_stale (TTL 6h)
    │     ├─ Circuit Breaker check
    │     ├─ _update_trailing_stops
    │     ├─ _manage_master_exits
    │     └─ _look_for_master_entries_advanced :
    │           ├─ Profil régime (+ blend transition)
    │           ├─ Filtre base (score/conf/RR)
    │           ├─ Ensemble vote
    │           ├─ Correlation block
    │           ├─ MTF confluence
    │           └─ Kelly sizing → _execute_entry
    └─ Legacy portfolios (securite/libre)
```

---

## Settings DB importants

| Clé | Type | Description |
|---|---|---|
| `auto_trade_master` | bool-str | Bot Maître actif |
| `budget_master` | float-str | Capital courant (évolue avec P&L) |
| `budget_master_initial` | float-str | Capital de référence pour ROI |
| `risk_master` | float-str | Override user du risk_pct |
| `binance_api_key` | encrypted | Clé API (préfixe `enc:`) |
| `binance_api_secret` | encrypted | Secret API |
| `auto_trade_securite` | bool-str | Portefeuille legacy Sécurité |
| `auto_trade_libre` | bool-str | Portefeuille legacy Libre |

---

## Conventions

### UI / Textes
- Toutes les chaînes UI sont en **français**.
- Les logs (`logger.info/error`) avec préfixe `[BotMaitre]`.
- Pas d'emojis dans les logs (problèmes encoding Windows console).

### Code
- Pas de docstrings multi-paragraphes — concision.
- Pas de commentaires qui paraphrasent le code.
- Les modules construisent des widgets Kivy programmatiquement quand la logique est dynamique, KV pour le layout statique.
- Dataclasses pour les structures de données.

---

## Opérations sensibles — faire ATTENTION

- **Ne jamais** toucher `budget_master_initial` sauf via `reset_master_initial()` dans settings.
- **Ne jamais** inclure `sum(entry_usdt)` dans le calcul de `total_equity` (ce serait un double-comptage — le `budget_master` contient déjà l'argent investi).
- **Ne jamais** créer un `BinanceClient` directement — passer par `exchange.get_client()` pour bénéficier du singleton.
- **Ne jamais** utiliser `place_stop_limit_order` pour les SL auto — utiliser `place_stop_loss_market` (gap-safe).
- **Ne jamais** skip le `is_defaults` check de Kelly — le bot doit basculer en cold start.
- Modifier les `REGIME_PROFILES` nécessite re-backtest.

---

## Lancer le projet

```bash
# Desktop — app Kivy
python main.py

# Validation stratégie
python run_backtest.py --days 90 --regime --verbose

# Optimisation paramètres
python optimize_params.py --days 60 --regime --top 10

# Walk-forward (gold standard validation)
python optimize_params.py --days 120 --walk-forward --wf-window 30 --wf-step 15
```

## Tests manuels

Aucune suite de tests automatisés actuellement (limitation documentée dans `PROJECT_STATE.md`). Les modules sont validés manuellement via :
- `python -c "import core.X"` pour compile check
- Fonctions de test inline dans chaque module (via interactive Python)
- Backtest complet end-to-end sur données Binance live
