# 05 — Architecture Technique

> Stack figée, ne pas changer sans raison majeure documentée.
> Toute évolution doit respecter la contrainte mobile + local + zéro
> dépendance lourde.

---

## Stack figée

| Couche | Tech | Pourquoi |
|---|---|---|
| Langage | **Python 3.11 / 3.12** | Buildozer ne supporte pas 3.14 ; 3.11 et 3.12 supportés |
| UI | **Kivy 2.3.1 + KV** | Mobile-first, cross-platform, pas de dépendance lourde |
| Build Android | **Buildozer + python-for-android** | Standard Kivy ; CI GitHub Actions |
| Données marché | **Binance public klines + CoinGecko REST** | Gratuit, sans clé API |
| Exécution ordres | **Binance API v3** (signé HMAC) | Officiel, fiable |
| Indicateurs techniques | **Pure Python** (RSI, MACD, BB, ATR, Stoch, EMA, SMA) | **Zéro dépendance scientifique** (pas NumPy ni pandas) |
| Persistance | **SQLite WAL** (stdlib) | Robuste, atomique, pas de serveur |
| Crypto | **PBKDF2-SHA256 + XOR + base64** (stdlib `hashlib`) | Pas de dépendance ; obfuscation au repos |
| HTTPS | **urllib stdlib + certifi** | `core/net.py` centralisé |
| Notifications | **Telegram API via urllib** | Gratuit, instantané |
| Logging | **logging stdlib + TimedRotatingFileHandler** | Simple, fiable |
| Tests | **pytest** | Standard Python |

**Dépendances obligatoires** (`requirements.txt` minimal) :
```
kivy>=2.3.0
requests>=2.31.0
```

**Dépendances Android additionnelles** (`buildozer.spec`) :
```
python3, kivy==2.3.0, openssl, certifi
```

---

## Layout des modules

### Structure du projet

> **Note de nommage** : l'application s'appelle officiellement
> **Emeraude** (toutes les UI, notifications, rapports utilisent ce
> nom). Le dossier code historique `MstreamTrader/` et le repo `Mstream`
> conservent leur nom le temps d'un rename progressif (renommer du code
> live = risque de casser l'historique git, les builds et la
> persistence Android). Le rename complet repo + dossier est planifié
> dans un palier ultérieur.

```
Mstream/                              # Racine du repo (à renommer Emeraude)
├── Emeraude/                         # Cahier des charges (CE DOSSIER)
├── docs/                             # Doc historique technique
├── MstreamTrader/                    # Code app — sera Emeraude/ après rename
│   ├── main.py                       # Entry point Kivy app
│   ├── run_backtest.py               # CLI backtest
│   ├── optimize_params.py            # CLI grid search
│   ├── buildozer.spec                # Config Android
│   ├── requirements.txt
│   ├── core/                         # Cœur métier (28 modules)
│   │   ├── adaptive.py               # Thompson, UCB, RegimeMemory
│   │   ├── audit.py                  # Audit trail JSON 30j
│   │   ├── auto_trader.py            # Orchestration cycle 60min
│   │   ├── backtest.py               # Moteur backtest
│   │   ├── backup.py                 # Backup DB + restore atomique
│   │   ├── checkpoint.py             # Recovery après crash
│   │   ├── circuit_breaker.py        # 4 niveaux de protection
│   │   ├── correlation.py            # Matrice corrélation dynamique
│   │   ├── crypto.py                 # PBKDF2 + XOR pour clés API
│   │   ├── database.py               # SQLite WAL, 14 tables
│   │   ├── ensemble.py               # 3 stratégies + vote pondéré
│   │   ├── equity_history.py         # Snapshot quotidien capital
│   │   ├── exchange.py               # Connecteur Binance signé
│   │   ├── export.py                 # Export CSV trades
│   │   ├── health.py                 # Health checks continus
│   │   ├── indicators.py             # RSI, MACD, BB, ATR, Stoch, EMA
│   │   ├── logging_setup.py          # Logger rotatif
│   │   ├── market_data.py            # CoinGecko + Binance klines
│   │   ├── metrics.py                # Sharpe, Sortino, Calmar, PF
│   │   ├── mtf.py                    # Multi-Timeframe Confluence
│   │   ├── net.py                    # SSL_CTX partagé
│   │   ├── notifications.py          # Telegram bot
│   │   ├── paper_mode.py             # Ledger isolé virtuel
│   │   ├── paths.py                  # Storage Android-safe
│   │   ├── position_sizing.py        # Kelly Fractional + Vol Targeting
│   │   ├── regime.py                 # Bull/Bear/Neutral via EMA200 BTC
│   │   ├── retry.py                  # Décorateur exponentiel
│   │   ├── signals.py                # Scoring multi-indicateurs
│   │   ├── validation.py             # Validation settings (11 rules)
│   │   └── walk_forward.py           # Walk-forward analysis
│   ├── screens/                      # UI Kivy (5 écrans)
│   │   ├── dashboard_screen.py
│   │   ├── signals_screen.py
│   │   ├── portfolio_screen.py
│   │   ├── settings_screen.py
│   │   ├── backtest_screen.py
│   │   └── toast.py                  # Popup central auto-dismiss
│   ├── kv/                           # Layouts Kivy
│   │   ├── dashboard.kv
│   │   ├── signals.kv
│   │   ├── portfolio.kv
│   │   └── settings.kv
│   └── tests/                        # 311 tests pytest
│       ├── test_adaptive.py
│       ├── test_audit.py
│       ├── test_auto_trader.py
│       └── ... (20 fichiers tests)
├── .github/workflows/                # CI
│   ├── tests.yml                     # pytest sur 3.11 + 3.12
│   └── build-apk.yml                 # Buildozer + artifact APK
├── README.md
├── CLAUDE.md
└── .gitignore
```

---

## Persistance : SQLite local + chiffrement

### 14 tables actuelles

1. `settings` (key/value, certaines chiffrées via préfixe `enc:`)
2. `portfolio` (positions manuelles utilisateur)
3. `trades` (ledger complet : MANUAL, AUTO_ENTRY_MASTER, etc.)
4. `signals_log` (historique des signaux)
5. `price_alerts` (alertes prix utilisateur)
6. `open_positions` (positions auto par portfolio_type)
7. `auto_trader_log` (journal décisions bot)
8. `audit_log` (audit trail structuré JSON)
9. `bot_checkpoints` (snapshots état volatile)
10. `equity_history` (capital quotidien)
11. `strategy_performance` (Thompson α/β par stratégie/régime)
12. `param_adjustments` (UCB profils paramétriques)
13. `regime_memory` (performance par régime)
14. `paper_master_*` (positions virtuelles paper mode)

### Storage Android-safe

Module : `core/paths.py`

Sur Android, le storage par défaut (bundle APK) est **volatile**. On
utilise donc `app_storage_path()` (= `/data/data/<package>/files/`)
qui est :
- Privé à l'app
- Persistant
- Survit aux mises à jour de l'APK
- Effacé seulement à la désinstallation

Sur desktop, on garde le path projet (`Path(__file__).parent.parent.parent`)
pour le développement.

### Chiffrement clés API

Module : `core/crypto.py`

- Algorithme : PBKDF2-SHA256 (100 000 itérations) + XOR stream
- Sel : 32 bytes aléatoires stockés dans `.mstream_salt` (file séparé,
  permission 0o600 sur POSIX)
- Préfixe `enc:` en DB pour distinguer chiffré vs clair (compat
  ascendante)
- Pas de cryptographie forte (pas de besoin pour obfuscation locale).
  **À renforcer** : migration vers Android KeyStore via pyjnius
  (palier 4 de la roadmap).

---

## Threading et concurrence

### 2 threads principaux

1. **Thread Kivy main** : UI, événements, animations.
2. **Thread `BotMaitre` daemon** : cycle 60 min, fetch + analyse +
   décision + exécution.

### Locks

- `AutoTrader._lock` (`threading.Lock`) protège `_latest_prices` et
  `_latest_signals` (écrits par main thread, lus par daemon).
- DashboardScreen `_fetch_lock` : anti-spam pour éviter plusieurs
  fetchs concurrents.

### Communication inter-threads

- **Daemon → UI** : `Clock.schedule_once(lambda dt: ..., 0)` pour
  toute mise à jour UI depuis le daemon.
- **UI → Daemon** : `auto_trader.update_market_data(...)` (thread-
  safe via `_lock`).

### Audit logger asynchrone

Module : `core/audit.py`

L'audit utilise une `queue.Queue` + worker thread dédié pour ne pas
bloquer le bot lors d'écritures DB. Mode sync en fallback.

---

## CI/CD

### Workflows GitHub Actions

#### 1. `.github/workflows/tests.yml`

Déclenchement : push sur main + PR.

```yaml
matrix: [3.11, 3.12]
steps:
  - checkout
  - setup-python
  - pip install pytest
  - pytest tests/ -v --tb=long → upload pytest-output.txt
  - python -m compileall core/ tests/ ...
```

#### 2. `.github/workflows/build-apk.yml`

Déclenchement : push sur main + tags `v*` + manual dispatch.

```yaml
runner: ubuntu-22.04
steps:
  - checkout
  - setup python 3.11
  - setup java 17
  - apt install dépendances Buildozer
  - cache ~/.buildozer
  - pip install buildozer cython==0.29.36
  - buildozer android debug
  - upload mstreamtrader-debug-apk artifact
  - if tag : create release with APK attached
```

**Performance** :
- Tests : ~2-3 min
- Premier build APK : ~30 min (download SDK/NDK)
- Builds suivants : ~5-10 min (cache)

---

## Principes architecturaux non-négociables

### 1. **Zéro dépendance scientifique lourde**

Pas de NumPy, pandas, scipy, scikit-learn, TensorFlow, PyTorch. Tout
en pure Python + stdlib.

**Pourquoi** : Buildozer / python-for-android compile mal ces
dépendances, augmentent l'APK de 100+ MB, allongent le build à
1h+. Le projet a démontré qu'on peut tout faire en pure Python.

### 2. **Imports paresseux dans les méthodes critiques**

Pour éviter des crashes au démarrage Android :

```python
def _fetch_data(self):
    from core import market_data  # ← lazy import
    ...
```

Plutôt qu'au top-level. Permet à l'app de démarrer même si un
module a un problème.

### 3. **urllib (stdlib) pour les appels HTTP dans `core/`**

Pas `requests` qui ajoute des dépendances. `core/net.py` centralise
le SSL context (certifi + system CAs Android).

### 4. **SQLite WAL pour concurrence**

Mode `WAL` activé via `PRAGMA journal_mode=WAL` permet
lectures concurrentes pendant écriture. Critique pour
DB partagée entre thread daemon et UI.

### 5. **Atomic SQL via `BEGIN IMMEDIATE` + retry exponentiel**

Module : `database.increment_numeric_setting()`

Pour incrémenter atomiquement un setting numérique (budget +
PnL réalisé), on utilise `BEGIN IMMEDIATE` (lock immédiat) avec
5 retries exponentiels sur `SQLITE_BUSY`.

---

## Diagramme architectural complet

```
                    ┌────────────────────────────────────┐
                    │         CIRCUIT BREAKER            │
                    │   HEALTHY/WARNING/TRIGGERED/FROZEN  │
                    └────────────┬───────────────────────┘
                                 │ autorise / bloque
                                 ▼
   ┌──────────────┐    ┌────────────────────────┐    ┌──────────────┐
   │    HEALTH    │───▶│      BOT MAITRE         │◀───│  CHECKPOINT  │
   │   CHECKS     │    │     (cycle 60 min)      │    │   (recovery) │
   └──────────────┘    └────────────┬───────────┘    └──────────────┘
                                    │
       ┌────────────────────────────┼────────────────────────────┐
       ▼                            ▼                            ▼
┌──────────────┐           ┌────────────────┐           ┌────────────────┐
│    REGIME    │           │  CORRELATION   │           │    ENSEMBLE    │
│ EMA200 BTC   │           │     MATRIX     │           │  (3 strats     │
│ Bull/Bear/Neu│           │ (vraie diver.) │           │   adaptatif)   │
└──────────────┘           └────────────────┘           └────────────────┘
       │                            │                            │
       └────────────┬───────────────┴────────────┬───────────────┘
                    ▼                            ▼
           ┌─────────────────┐           ┌──────────────────┐
           │ POSITION SIZING │           │   AUDIT TRAIL    │
           │ Kelly+Vol-Tgt   │           │ JSON 30j queryable│
           └─────────────────┘           └──────────────────┘
                    │                            │
                    └────────────┬───────────────┘
                                 ▼
                    ┌────────────────────┐
                    │  ADAPTIVE AGENT     │
                    │  (Thompson, UCB,    │
                    │   Régime Memory)    │
                    └────────┬────────────┘
                             │
                             ▼
                    ┌────────────────────┐
                    │      SQLITE WAL     │
                    │   14 tables, locale │
                    │   chiffrée pour clés│
                    └─────────────────────┘
```

---

## Sécurité

### Modèle de menace

| Menace | Contre-mesure actuelle | Statut |
|---|---|---|
| Attaquant lit la DB sans le téléphone | PBKDF2 + XOR + sel séparé | ✅ Suffit (obfuscation locale) |
| Téléphone rooté + accès code + DB + sel | Aucune (XOR cassable) | ⚠️ Migration KeyStore prévue palier 4 |
| Capture écran révèle clé API | Champs vides au reload, password=True | ✅ Fixé 2026-04-25 |
| Clé API leakée par log | logging masque les valeurs sensibles | ✅ |
| Réseau MITM | HTTPS + certifi pour CAs | ✅ |
| Slippage adverse | `place_stop_loss_market` (pas LIMIT) | ✅ Gap-safe |
| Bot prend trop de positions | `max_positions=1` + correlation_block | ✅ |
| Bug logique → drawdown massif | Circuit Breaker 4 niveaux | ✅ |
| App crash perd l'état | Checkpoint + auto-recovery | ✅ |
| User active argent réel par accident | Confirmation double-tap | ✅ Fixé 2026-04-25 |

### Permissions Binance recommandées

L'utilisateur doit créer une clé API Binance avec **uniquement** :
- ✅ **READ** (lire le solde)
- ✅ **TRADE** (passer des ordres spot)
- ❌ **WITHDRAW** (NE PAS activer — pas besoin, et limite l'impact si fuite)

Whitelist IP optionnelle si l'utilisateur a une IP fixe.

---

## Roadmap technique (paliers)

### Court terme (palier 1-2)
- Trading réel sur 20 USD
- Stabilisation 30 jours
- Création écran "IA / Apprentissage"
- Connexion adaptive ↔ ensemble vote (vérifier intégration)

### Moyen terme (palier 3-4)
- Refonte scoring (rebalance pondérations)
- Pullback detection
- Volume confirmation
- Migration KeyStore Android

### Long terme (palier 5+)
- Backup chiffré cloud opt-in
- Multi-exchanges (Coinbase, Kraken)
- Tests Android automatisés (Espresso)
- Monitoring production (Sentry-like local)

---

*v1.0 — 2026-04-25*
