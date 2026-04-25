# État Réel du Projet — Code vs Documentation

> Document de vérité croisant chaque fonctionnalité avec son statut réel dans le code source.
> Mis à jour : 2026-04-25 (post-itération mission).
>
> **Stats du projet** : ~12 550 lignes Python (incluant tests) · 28 modules `core/` · 5 écrans Kivy · 311 tests pytest.
>
> Historique récent des audits :
> - Itérations #5-#17 : durcissement tests, code mort retiré, exceptions ciblées, agent adaptatif Thompson, cache OHLCV. Tests passés de 57 à 306.
> - **V14 (avril 2026)** : intégration features production — Paper mode, Telegram, Backup DB, Retry exponentiel, Validation settings, Logs rotatifs, Partial exits, Equity history, Export CSV, Audit async.
> - **Sprint Android (avril 2026)** : déploiement APK via GitHub Actions.
>   - Récursion infinie logging (Kivy capture stderr) → console=False
>   - Emojis non rendus sur Roboto Android → font registration limitée à Windows
>   - Persistance DB perdue entre sessions → nouveau module `core/paths.py` qui détecte Android et utilise `app_storage_path()`
>   - SSL HTTPS échouait silencieusement → `core/net.py` centralise SSL_CTX (certifi + system CAs + fallback)
>   - 31 emojis bouton/labels remplacés par texte universel
>   - Notifications fixes en bas → toast central auto-dismiss (`screens/toast.py`)
>   - R/R 0.5x sur "ACHAT FORT" → garantie min_rr=2.0 dans `_compute_stop_take`, downgrade si <1.5
>   - `_qualifies` exigeait STRONG_BUY only → accepte BUY+STRONG_BUY (score discrimine)
>   - Backtest 0 trade → filtres avancés OFF en mode démo
> - **Itération mission (2026-04-25)** : audit 20 dimensions, 311/311 tests.
>   - 🔴 P0 : `notifications.py` urlopen sans SSL_CTX → Telegram cassé sur Android. Fix appliqué.
>   - 🟠 P1 : `backup.py` n'avait pas de `restore_from_backup()` (critère terminaison #17 invalidé). Fonction ajoutée avec rollback atomique + 5 tests.
>   - 🟠 P1 : doc périmée (s'arrêtait à #17). Mise à jour.
>   - 🟡 P2 reportés : Sharpe/PF stratégie sur 365j (calibration), KeyStore Android, paper mode 30j, APK 24h continu.
> - **Itération #3 (revue code)** : 3 bugs trouvés en revue manuelle — `signals.py:260` `max(SL_atr, support*0.995)` resserrait le SL au lieu de l'élargir (fix : `min`) ; `optimize_params.py` utilisait `BacktestConfig()` defaults qui activaient ensemble/mtf/correlation, rendant le grid search inutile (0 trades sur 240 configs) ; `auto_trader._run_loop` perdait les tracebacks (`logger.error` → `logger.exception`).
> - **Itération #4 (audit profond)** : 10 dimensions vérifiées (mutable defaults, == None, bare except, assert prod, divisions, threading, cohérence inter-modules). Code Python propre, aucun antipattern critique. Bug stratégique identifié : score EMA 50 ne pèse que ±19 sur 100 max → BUY en downtrend possible. Option `require_uptrend_for_buy` ajoutée à `signals.analyze()` et `BacktestConfig`.
> - **Itération #5 (refonte stratégie data-driven)** : analyse des 6 trades perdants — 4 trades **ouverts simultanément** sur BTC/ETH/SOL/BNB le 31/01 16:00 (corrélation 0.9+), tous SL hit en cascade. Test config gagnante : `correlation_block + max_positions=1` produit Sharpe +2.16 sur 60j et +0.29 sur 365j. **MAIS walk-forward 365j (10 fenêtres 30j) verdict : NON ROBUSTE** — consistency 30 %, avg Sharpe -0.91, avg PF 0.83. La stratégie multi-indicateurs (RSI+MACD+BB+Stoch+EMA) **n'a pas d'edge prouvé**. Backtest UI aligné sur LIVE (correlation_block=True, max_positions=1) pour mesure honnête. **Refonte profonde requise** (pullback-only, volume, MTF strict) — chantier dédié.

---

## 🎯 Vue d'ensemble

| Catégorie | Implémenté | Intégré | Testé | Documenté |
|---|:-:|:-:|:-:|:-:|
| Moteur de données (CoinGecko + Binance) | ✅ | ✅ | ✅ | ✅ |
| Indicateurs techniques (RSI/MACD/BB/ATR/Stoch/EMA) | ✅ | ✅ | ✅ 26 tests | ✅ |
| Moteur de signaux (scoring multi-indicateurs) | ✅ | ✅ | ✅ 30 tests | ✅ |
| Bot Maître (autonome, thread daemon) | ✅ | ✅ | ✅ 19 tests | ✅ |
| Chiffrement clés API Binance | ✅ | ✅ | ✅ 15 tests | ✅ |
| Circuit Breaker 4 niveaux | ✅ | ✅ | ✅ | ✅ |
| Kelly Criterion Fractional | ✅ | ✅ | ✅ | ✅ |
| Dynamic Correlation Matrix | ✅ | ✅ | ✅ | ✅ |
| Ensemble Voting (3 stratégies) | ✅ | ✅ | ✅ 22 tests | ✅ |
| Multi-Timeframe Confluence | ✅ | ✅ | ✅ 18 tests | ✅ |
| Filtre Régime + Transition | ✅ | ✅ | ✅ 18 tests | ✅ |
| Audit Trail structuré | ✅ | ✅ | ✅ 14 tests | ✅ |
| Health Checks continu | ✅ | ✅ | ✅ | ✅ |
| Checkpointing + Auto-Recovery | ✅ | ✅ | ✅ | ✅ |
| **Agent Adaptatif (Thompson + UCB + Memory)** | ✅ | ✅ | ✅ | ✅ |
| Cache OHLCV per-cycle | ✅ | ✅ | ✅ | ✅ |
| Backtesting Engine | ✅ | — | ✅ | ✅ |
| Walk-Forward Analysis | ✅ | ✅ CLI | ✅ 4 tests | ✅ |
| Grid Search optimizer | ✅ | ✅ CLI | ✅ | ✅ |
| Checkpointing + Auto-Recovery | ✅ | ✅ | ✅ 12 tests | — |
| UI Kivy (4 écrans) | ✅ | ✅ | manuel | ✅ |
| Tests unitaires pytest | ✅ | ✅ | ✅ **306/306** | — |
| Notifications Telegram | ✅ | ✅ | ✅ 13 tests | docs/ADAPTIVE |
| Logs rotatifs fichier | ✅ | ✅ | — | — |
| Backup DB automatique | ✅ | ✅ | ✅ 8 tests | — |
| Paper Trading mode séparé | ✅ | ✅ | ✅ integ | — |
| Retry Binance exponentiel | ✅ | ✅ | ✅ 14 tests | — |
| Validation configs user | ✅ | ✅ | ✅ 11 tests | — |
| Partial exits (TP1 50% + runner) | ✅ | ✅ | — | — |
| Backtesting UI Screen | ✅ | ✅ | — | — |
| Dashboard web | ❌ | ❌ | — | à faire |
| Type hints mypy strict | ❌ | ❌ | — | à faire |
| CI/CD GitHub Actions | ❌ | ❌ | — | à faire |

**Légende** :
- ✅ Fait et vérifié
- ❌ Absent du code
- — Non applicable

---

## 📁 Inventaire du code source

### `core/` — Cœur du bot (20 modules, ~6 717 lignes)

| Module | Lignes | Rôle | Dépend de | Utilisé par |
|---|---:|---|---|---|
| `auto_trader.py` | ~1380 | **Bot Maître** — orchestre tout + cache OHLCV + adaptive + MTF aligné + partial exits + notifications | tous les institutional + database/exchange | `main.py`, screens |
| `adaptive.py` | 632 | **Agent Adaptatif** — Thompson + UCB + Regime Memory + `record_trade_outcome` API thread-safe | database | auto_trader, ensemble |
| `database.py` | ~740 | SQLite 13 tables + migrations auto (open_positions 16 colonnes inc. tp1_price/tp1_taken) | crypto | tous |
| `circuit_breaker.py` | 337 | Kill switch 4 niveaux + `get_state_snapshot()` atomique | — | auto_trader, checkpoint |
| `notifications.py` | ~220 | **Telegram Bot** — envoi async, rate-limited, events ENTRY/EXIT/CB/DD | database | auto_trader |
| `paper_mode.py` | ~110 | **Paper Trading mode** — ledger séparé, flag persistent, zero risque | database | auto_trader, UI |
| `retry.py` | ~120 | Décorateur retry exponentiel pour erreurs Binance transitoires | exchange | exchange |
| `validation.py` | ~165 | Validation des configs user (budget, risk, clés, tokens) | database | screens, UI |
| `logging_setup.py` | ~100 | Logger rotatif fichier (30 jours rétention) + console | — | main |
| `backup.py` | ~100 | Snapshot SQLite atomique toutes les 24h, rétention 7 jours | database | auto_trader |
| `database.py` | 661 | SQLite 9 tables, atomic increment, chiffrement | `crypto.py` | tous |
| `backtest.py` | 545 | Moteur simulation multi-coins | regime, indicators, signals, metrics | run_backtest, optimize_params |
| `exchange.py` | 502 | Client Binance v3 + singleton + precisions | database, crypto | auto_trader, screens |
| `audit.py` | 376 | **Audit trail structuré** | database | auto_trader |
| `signals.py` | 369 | Scoring multi-indicateurs | indicators | dashboard, auto_trader, backtest |
| `ensemble.py` | 355 | **3 sous-stratégies votent** | indicators | auto_trader |
| `position_sizing.py` | 330 | **Kelly Fractional + Vol Targeting** | indicators, database | auto_trader |
| `metrics.py` | 323 | Sharpe/Sortino/Calmar/R-multiples | — | backtest, run_backtest, optimize_params |
| `indicators.py` | 313 | RSI/MACD/BB/ATR/Stoch/EMA pure Python | — | tous |
| `circuit_breaker.py` | 320 | **Kill switch 4 niveaux + auto-recovery** (getters thread-safe) | — | auto_trader |
| `regime.py` | 309 | **Bull/Bear/Neutral + transition** | indicators | auto_trader, backtest |
| `market_data.py` | 230 | CoinGecko + Binance public klines | — | tous |
| `mtf.py` | 226 | **Multi-Timeframe Confluence** | indicators | auto_trader |
| `health.py` | 215 | Health checks APIs + sanity | market_data, circuit_breaker | auto_trader |
| `walk_forward.py` | 211 | **Walk-Forward Analysis** | backtest | optimize_params |
| `correlation.py` | 211 | Pearson correlation matrix | — | auto_trader, backtest (indirect) |
| `checkpoint.py` | 197 | Snapshot état volatile + recovery | database, circuit_breaker, auto_trader | auto_trader |
| `crypto.py` | 118 | PBKDF2-SHA256 + XOR stream cipher | — | database, exchange |

### `screens/` — Interface Kivy (4 écrans, ~1 056 lignes)

| Module | Lignes | Refresh | Responsabilité |
|---|---:|---|---|
| `portfolio_screen.py` | 359 | 35 s | Bot Maître stats + positions + journal + anciens portefeuilles |
| `settings_screen.py` | 341 | on_enter | Clés API (chiffrées), budget Bot Maître, switches |
| `signals_screen.py` | 195 | 35 s | Liste des cartes signaux triées |
| `dashboard_screen.py` | 161 | 30 s | Dashboard principal + fetch + threading.Lock anti-spam |

### Scripts racine

| Fichier | Lignes | Rôle |
|---|---:|---|
| `main.py` | 318 | App Kivy, CoinListWidget, TradeDialog, ScreenManager |
| `optimize_params.py` | 398 | Grid search + Walk-Forward CLI |
| `run_backtest.py` | 209 | Backtest CLI avec rapport textuel |

### Layouts KV

| Fichier | Ce qu'il contient |
|---|---|
| `kv/dashboard.kv` | Layout écran principal |
| `kv/portfolio.kv` | Layout écran portefeuille (y compris Bot Maître) |
| `kv/settings.kv` | Layout configuration |
| `kv/signals.kv` | Layout liste des signaux |

---

## 🔬 Statut des features Institutional Grade

Chaque case ✅ est **vérifiée** via `grep` dans le code source — pas une affirmation doc.

### 1. Régime Bull/Bear/Neutral
- ✅ Module existe : `core/regime.py` (detect_regime, get_profile, describe)
- ✅ Appelé depuis auto_trader.py : `_refresh_regime_if_stale()` avec TTL 6h
- ✅ Intégré dans backtest.py : `config.use_regime_filter` + profils adaptatifs
- ✅ Documenté : [REGIME.md](REGIME.md)

### 2. Détection de transition
- ✅ Module existe : `regime.detect_regime_transition()`
- ✅ Appelé depuis auto_trader.py : `_refresh_regime_if_stale()` si `use_regime_transition=True`
- ✅ Blending de profil : dans `_look_for_master_entries_advanced` si transition_score ≥ 0.5
- ✅ Documenté : [REGIME.md § Transition](REGIME.md)

### 3. Kelly Criterion Fractional
- ✅ Module existe : `core/position_sizing.py` (fractional_kelly, optimal_position_size)
- ✅ Appelé depuis auto_trader.py : `_look_for_master_entries_advanced` si `use_kelly_sizing=True`
- ✅ Cold start protection : `is_defaults=True` → bascule à 1 % du budget max
- ✅ Matching BUY/SELL correct : via `open_positions.closed_at` ± 2 sec
- ✅ Documenté : [INSTITUTIONAL.md § 2](INSTITUTIONAL.md)

### 4. Dynamic Correlation Matrix
- ✅ Module existe : `core/correlation.py` (compute_correlation_matrix, is_too_correlated)
- ✅ Appelé depuis auto_trader.py : construite dans `_look_for_master_entries_advanced`
- ✅ Blocage si > 0.75 avec positions ouvertes
- ✅ Audit log : `audit.log_correlation_block()`
- ✅ Documenté : [INSTITUTIONAL.md § 3](INSTITUTIONAL.md)

### 5. Ensemble Voting
- ✅ Module existe : `core/ensemble.py` (3 sous-stratégies + vote pondéré régime)
- ✅ Appelé depuis auto_trader.py : `_compute_ensemble_vote()` dans la boucle candidates
- ✅ Qualification : `ensemble.is_ensemble_qualified(decision, min_agreement=2, min_score=30)`
- ✅ Documenté : [INSTITUTIONAL.md § 4](INSTITUTIONAL.md)

### 6. Multi-Timeframe Confluence
- ✅ Module existe : `core/mtf.py` (analyze_confluence, is_confluence_valid_for_long)
- ✅ Appelé depuis auto_trader.py : `_compute_mtf()` après ensemble + correlation
- ✅ Timeframes : 1h (5 j) + 4h (30 j) + 1d (180 j)
- ✅ Rejet si TF long bearish fort
- ✅ Documenté : [INSTITUTIONAL.md § 5](INSTITUTIONAL.md)

### 7. Circuit Breaker 4 niveaux
- ✅ Module existe : `core/circuit_breaker.py` (HEALTHY/WARNING/TRIGGERED/FROZEN)
- ✅ Appelé depuis auto_trader.py : `get_circuit_breaker()` partout
- ✅ Report capital : `cb.report_capital(total_equity)` (fix P0.1 — pas de double-comptage)
- ✅ Report trades : `cb.report_trade_result(pnl, exit_reason, avg_loss)`
- ✅ Report API errors : `cb.report_api_error(msg)` sur failures
- ✅ Auto-recovery : `cb.auto_recover_check()` appelé à chaque cycle
- ✅ Documenté : [INSTITUTIONAL.md § 1](INSTITUTIONAL.md)

### 8. Audit Trail
- ✅ Module existe : `core/audit.py` (15 types events, JSON in/out/reasoning)
- ✅ Table DB `audit_log` créée automatiquement dans `init_db()`
- ✅ 11 helpers appelés depuis auto_trader.py (log_signal_analyzed, log_entry_executed, etc.)
- ✅ Purge automatique : `purge_old_events(days=30)` appelée tous les 24 cycles
- ✅ Documenté : [INSTITUTIONAL.md § 8](INSTITUTIONAL.md)

### 9. Health Checks
- ✅ Module existe : `core/health.py` (ping Binance, ping CoinGecko, sanity prix)
- ✅ Appelé depuis auto_trader.py : `_run_periodic_tasks()` chaque cycle
- ✅ Remontée au circuit breaker : `cb.report_anomaly()` si checks fail
- ✅ Documenté : [INSTITUTIONAL.md § 9](INSTITUTIONAL.md)

### 10. Checkpointing & Recovery
- ✅ Module existe : `core/checkpoint.py` (BotSnapshot, save_snapshot, auto_recover_on_startup)
- ✅ Table DB `bot_checkpoints` créée à `init_checkpoint_table()`
- ✅ Save : `_run_periodic_tasks()` tous les 6 cycles (≈ 6h)
- ✅ Recovery au startup : `start()` appelle `auto_recover_on_startup()`
- ✅ Si snapshot > 24h : ignoré (repart de zéro)
- ✅ Documenté : [INSTITUTIONAL.md § 10](INSTITUTIONAL.md)

---

## 🔒 Sécurité — Statut

| Mesure | Statut | Vérification |
|---|:-:|---|
| Clés API chiffrées au repos | ✅ | `core/crypto.py` + `database.set_setting_encrypted()` |
| Migration auto clés en clair → chiffrées | ✅ | `_migrate_encrypt_api_keys()` dans `init_db()` |
| Préfixe `enc:` pour compat ascendante | ✅ | Constant `ENC_PREFIX` dans crypto.py |
| Salt hors DB (fichier séparé 0o600) | ✅ | `.mstream_salt` avec `os.chmod(0o600)` |
| STOP_LOSS market (gap-safe) | ✅ | `place_stop_loss_market` au lieu de `place_stop_limit_order` |
| Singleton Binance client | ✅ | `_client_cache` + `invalidate_client_cache()` |
| Précisions Binance dynamiques | ✅ | `/api/v3/exchangeInfo` + fallback table |
| SQL atomique avec retry | ✅ | `increment_numeric_setting` avec BEGIN IMMEDIATE + exponential backoff |
| Total equity correct | ✅ | Fix P0.1 appliqué (`budget + unrealized`, pas `budget + entry_usdt + unrealized`) |
| Kelly cold start protection | ✅ | `is_defaults=True` → 1 % budget max |
| Kelly entry/exit matching correct | ✅ | Via `open_positions.closed_at` ± 2 sec tolerance |

---

## 🗂️ Base de données — 9 tables

| Table | Créée dans | Rôle |
|---|---|---|
| `settings` | `database.py init_db()` | Config key/value (inc. API keys chiffrées) |
| `portfolio` | `database.py init_db()` | Positions manuelles |
| `trades` | `database.py init_db()` | Ledger des trades (MANUAL + AUTO) |
| `signals_log` | `database.py init_db()` | Historique signaux analysés |
| `price_alerts` | `database.py init_db()` | Alertes prix utilisateur |
| `open_positions` | `database.py init_db()` | Positions ouvertes (master, securite, libre) |
| `auto_trader_log` | `database.py init_db()` | Journal décisions bot |
| `audit_log` | `audit.py init_audit_table()` | **Audit trail institutional** |
| `bot_checkpoints` | `checkpoint.py init_checkpoint_table()` | Snapshots état volatile |

---

## ⚠ Limites connues & TODO

### Limitations actives (par design ou contrainte)

| Limite | Raison | Impact |
|---|---|---|
| Cycle bot à 60 min | Aligné timeframe 1h des données d'analyse | Réactivité limitée en flash crash |
| Max 8 coins trackés | `DEFAULT_COINS` hardcodé | Pas de découverte auto de nouveaux assets |
| Pas de trading short | Spot uniquement | Inefficace en bear market prolongé |
| Régime requiert 200 j BTC daily | EMA 200 fiable | N/A en dev, OK en prod |
| Audit log ~200 events/jour | Chaque signal audité | Purge auto 30 j limite à ~6 000 lignes max |

### Fonctionnalités absentes (pas encore codées)

- ❌ **Tests unitaires** (pytest) — validation manuelle uniquement
- ❌ **Écran Backtest dans l'app Kivy** — actuellement CLI uniquement
- ❌ **Graphiques capital + équity curve** dans la UI
- ❌ **Notifications push Android** (`plyer.notification`)
- ❌ **Multi-exchange** (Kraken, Coinbase) — Binance only
- ❌ **Short positions** / futures trading
- ❌ **Détection automatique de nouveaux coins intéressants** — liste figée
- ❌ **Stop-loss hardware** (SL sur serveur Binance en plus du soft SL) — nécessite ajouter `place_stop_loss_market` systématiquement à l'entrée

### Améliorations potentielles documentées

- ✅ ~~Caching OHLCV partagé entre signals/ensemble/MTF~~ — **implémenté** (itération #6) via `_cached_ohlcv()` dans auto_trader.py : dédoublonne les fetches HTTP avec support de slicing intelligent (cache de `days=21` réutilisé pour `days=5`, etc.)
- Audit logger asynchrone (queue + worker) si volume augmente
- Scheduler séparé pour les tâches périodiques vs cycle principal
- Export CSV/Parquet du ledger pour analyse externe

---

## 🧪 Stratégie de test actuelle

**Aucun framework pytest/unittest**. La validation se fait à trois niveaux :

1. **Compile check** : `python -c "import core.X"` pour chaque module
2. **Smoke tests manuels** : fonctions inline testées via Python interactif
3. **End-to-end** : `run_backtest.py` sur données Binance réelles

Un CI avec `pytest` est prévu dans la roadmap mais pas encore implémenté.

---

## 📅 Historique des vagues de dev

| Vague | Contenu | Modules créés |
|---|---|---|
| **V0 — Initial** | Bot de base avec 2 portefeuilles (securite/libre) | Tous les modules de base |
| **V1 — Phase 1** | Bugs critiques + chiffrement + cycle 60 min | crypto.py, fixes |
| **V2 — Backtesting** | Moteur de backtest + metrics + grid search | backtest.py, metrics.py, run_backtest.py, optimize_params.py |
| **V3 — Régime + Optimizer** | Filtre Bull/Bear + grid search | regime.py (extension) |
| **V4 — Institutional Grade** | 10 techniques pro + intégration | 8 nouveaux modules + intégration complète |
| **V5 — Audit + fixes finaux** | 5 bugs P0 + 6 intégrations P1 | fixes cross-modules |
| **V6 — Audit continu #5** | 1 bug P0 (budget stale) + 3 P1 (thread-safety, exceptions) + 1 P2 (code mort) | hardening, −30 net lignes |
| **V7 — Audit continu #6** | Cache OHLCV per-cycle intelligent | −28 % HTTP calls/cycle, slicing automatique |
| **V8 — Agent adaptatif** | Thompson Sampling + UCB + Regime Memory | +587 lignes (adaptive.py), 3 tables DB, apprentissage en ligne |
| **V9 — Attribution correcte** | Fix fake partiel : votes persistés par position + crédit individuel | Migration DB open_positions + attribution réelle (divergence bandits prouvée) |
| **V10 — Audit continu #7** | Encapsulation adaptive + thread-safety CB snapshot + exceptions ciblées health | `record_trade_outcome()` unifié (lock interne), `get_state_snapshot()` atomique CB, dead code `on_trade_closed` retiré |
| **V11 — Audit continu #8** | Alignement MTF bot live ↔ backtest (soft pass si < 3 TF) + import mort retiré | Fin de divergence MTF avec backtest, exceptions MTF ciblées |
| **V12 — Phase complète** | 8 livraisons majeures : logs rotatifs + backup DB + paper mode + notifications Telegram + retry exponentiel + validation configs + tests pytest (48/48) + partial exits TP1 | +9 nouveaux modules, suite tests pytest, features production-grade |
| **V13 — Audit continu #9** | 4 issues post-V12 corrigées : (1) paper_mode réellement intégré au bot, (2) Kelly stats inclut AUTO_PARTIAL, (3) notifications CB transitions + DD pause, (4) realized_pnl agrège partial exits | Cohérence ledger paper/réel, Kelly non biaisé, alertes critiques actives |
| **V14 — Phase complète UX + Robustesse** | Phase D (UX) : Telegram UI + Paper UI + daily summary scheduling + emergency stop + export CSV + stats adaptive UI + equity history. Phase E : audit async worker + tests intégration end-to-end + risk parity confirmé. Phase F : Backtest UI Screen Kivy | +2 modules (`equity_history`, `export`), +1 écran Kivy (`backtest_screen`), 57/57 tests pytest, audit logger non-bloquant |

---

## ✅ Vérification visuelle de l'intégration

Tu peux toi-même vérifier que tout est bien branché :

```bash
cd MstreamTrader

# Chaque module compile
python -c "from core import auto_trader, backtest, regime, circuit_breaker, audit, health, checkpoint, position_sizing, correlation, mtf, ensemble, walk_forward; print('OK')"

# Le bot charge tous les switches à True
python -c "from core.auto_trader import MASTER_CONFIG; print(
    'ensemble:',     MASTER_CONFIG['use_ensemble'],
    'correlation:',  MASTER_CONFIG['use_correlation_block'],
    'kelly:',        MASTER_CONFIG['use_kelly_sizing'],
    'mtf:',          MASTER_CONFIG['use_mtf_confluence'],
    'transition:',   MASTER_CONFIG['use_regime_transition'],
)"

# Les tables audit/checkpoint sont créées
python -c "from core.database import init_db, get_connection; init_db(); 
with get_connection() as c:
    tables = [r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")]
    print(sorted(tables))"
```

Sortie attendue :
```
OK
ensemble: True correlation: True kelly: True mtf: True transition: True
['auto_trader_log', 'audit_log', 'bot_checkpoints', 'open_positions', 'portfolio', 'price_alerts', 'settings', 'signals_log', 'trades']
```

Si tu obtiens ces 3 sorties, **le projet est bel et bien dans l'état documenté**.
