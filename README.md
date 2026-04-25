# MstreamTrader

> **Bot de trading crypto autonome de niveau institutional grade, mobile-first.**
>
> 20 modules Python, 10 techniques algorithmiques pro, 8903 lignes de code, zero dépendance lourde.

---

## L'Idée

Les marchés crypto sont accessibles 24h/24, mais le cerveau humain ne l'est pas. La peur, la cupidité et la fatigue sabotent systématiquement les décisions de trading. MstreamTrader confie ton capital à un algorithme discipliné, rigoureux, et disponible en permanence — directement depuis ton téléphone Android.

Le projet répond à une question précise : **peut-on confier un capital à un bot mobile et le laisser le faire croître seul, avec la même rigueur qu'un hedge fund, sans abonnement cloud et sans dépendance à une API payante ?**

**Réponse : oui.**

---

## La Mission

**Rendre le trading algorithmique de niveau hedge fund accessible à tout investisseur particulier, depuis son téléphone, gratuitement.**

- Données de marché gratuites (Binance public klines + CoinGecko)
- Fonctionne sans compte Binance (mode simulation intégré)
- Tourne en local — aucune donnée envoyée à un serveur tiers
- Disponible sur Android (APK) et desktop (Windows/Linux/Mac)

---

## Le Bot Maître

Au cœur du projet : le **Bot Maître**, un moteur autonome qui exécute un cycle d'analyse toutes les 60 minutes dans un thread daemon indépendant.

Il orchestre **10 techniques de niveau institutional** :

| # | Technique | Module | Statut |
|---|---|---|---|
| 1 | Filtre de Régime Bull/Bear/Neutral | [core/regime.py](MstreamTrader/core/regime.py) | ✅ Intégré |
| 2 | Détection précoce de Transition de Régime | [core/regime.py](MstreamTrader/core/regime.py) | ✅ Intégré |
| 3 | Kelly Criterion Fractional + Volatility Targeting | [core/position_sizing.py](MstreamTrader/core/position_sizing.py) | ✅ Intégré |
| 4 | Dynamic Correlation Matrix (vraie diversification) | [core/correlation.py](MstreamTrader/core/correlation.py) | ✅ Intégré |
| 5 | Ensemble Voting (3 sous-stratégies votent) | [core/ensemble.py](MstreamTrader/core/ensemble.py) | ✅ Intégré |
| 6 | Multi-Timeframe Confluence (1h + 4h + 1d) | [core/mtf.py](MstreamTrader/core/mtf.py) | ✅ Intégré |
| 7 | Circuit Breaker Multi-Niveaux | [core/circuit_breaker.py](MstreamTrader/core/circuit_breaker.py) | ✅ Intégré |
| 8 | Audit Trail Structuré | [core/audit.py](MstreamTrader/core/audit.py) | ✅ Intégré |
| 9 | Health Checks Continu | [core/health.py](MstreamTrader/core/health.py) | ✅ Intégré |
| 10 | Checkpointing & Recovery | [core/checkpoint.py](MstreamTrader/core/checkpoint.py) | ✅ Intégré |

Bonus : **Walk-Forward Analysis** ([core/walk_forward.py](MstreamTrader/core/walk_forward.py)) pour valider la robustesse hors-sample avant déploiement.

Voir [docs/INSTITUTIONAL.md](docs/INSTITUTIONAL.md) pour le détail de chaque technique.

---

## Les Objectifs

### Objectif principal
Faire croître un capital crypto de façon totalement autonome, avec la discipline algorithmique d'un hedge fund et la protection d'un circuit breaker institutionnel.

### Objectifs secondaires

| Objectif | Technique utilisée |
|---|---|
| Discipline algorithmique | Règles fixes codées, pas de biais émotionnel |
| Protection du capital | Circuit Breaker 4 niveaux + Drawdown pause + Trailing SL ATR |
| Transparence totale | Audit Trail — chaque décision horodatée et traçable |
| Indépendance | Fetch autonome + Checkpointing + Auto-recovery |
| Croissance composée | Réinvestissement automatique des profits |
| Sécurité des fonds | Clés API chiffrées (PBKDF2) + STOP_LOSS market (gap-safe) |
| Vraie diversification | Matrice de corrélation dynamique (refuse corrélation > 0.75) |
| Position sizing optimal | Kelly Criterion Fractional (1/4 Kelly) |
| Robustesse stratégique | Ensemble Voting + MTF Confluence + Régime adaptatif |
| Validation scientifique | Backtesting + Walk-Forward + Grid Search |

---

## Les Fonctionnalités

### Application Mobile (Kivy)
Quatre écrans navigables, refresh automatique toutes les 30 s :

| Écran | Ce qu'on y fait |
|---|---|
| **📊 Dashboard** | Prix live, top signal, valeur portefeuille, stats |
| **⚡ Signaux** | Liste des 8 coins avec score et bouton TRADE |
| **💼 Portfolio** | Bot Maître + positions + historique + journal auto |
| **⚙ Configuration** | Clés Binance, budget Bot Maître, switches |

### Outils en ligne de commande

| Commande | Rôle | Durée typique |
|---|---|---|
| `python main.py` | Lance l'application Kivy | — |
| `python run_backtest.py --days 90` | Backtest historique avec toutes les métriques | ~15 s |
| `python run_backtest.py --regime --verbose` | Backtest + filtre régime + détail trades | ~30 s |
| `python optimize_params.py --days 60` | Grid search (~80 combinaisons) | ~2-5 min |
| `python optimize_params.py --walk-forward` | Grid search + walk-forward (robustesse OOS) | ~10-20 min |

### Indicateurs techniques
Tous calculés en pure Python (aucune dépendance) :
- **RSI** 14 — Relative Strength Index
- **MACD** 12/26/9 — avec histogramme
- **Bollinger Bands** 20, 2σ — avec bandwidth pour squeeze
- **ATR** 14 — Average True Range pour volatility
- **Stochastique** 14/3 — %K et %D
- **EMA** 12, 26, 50 — Moving averages exponentielles
- **Support / Résistance** — détection locale

### Scoring multi-indicateurs (signals.py)
Le score final (−100 à +100) combine les 5 indicateurs pondérés :
- RSI × 1.0 (±40 max)
- MACD × 1.0 (±25 max)
- Bollinger × 0.85 (±21 max)
- Stochastique × 0.75 (±20 max)
- EMA × 0.75 (±19 max)

Mappés en signaux :
- **≥ 50** → ACHAT FORT
- **20 à 49** → ACHAT
- **−20 à 19** → CONSERVER
- **−49 à −21** → VENTE
- **≤ −50** → VENTE FORTE

Chaque signal inclut Stop-Loss, Take-Profit, Ratio R/R et liste des raisons.

---

## Architecture Technique

```
                  ┌─────────────────────────────────────────┐
                  │            CIRCUIT BREAKER              │
                  │         (kill switch 4 niveaux)         │
                  └────────────────┬────────────────────────┘
                                   │ autorise / bloque
                                   ▼
   ┌──────────────┐       ┌────────────────────┐       ┌──────────────┐
   │    HEALTH    │──────▶│     BOT MAÎTRE     │◀──────│  CHECKPOINT  │
   │   CHECKS     │       │   (cycle 60 min)   │       │   (recovery) │
   └──────────────┘       └─────────┬──────────┘       └──────────────┘
                                    │
       ┌────────────────────────────┼────────────────────────────┐
       ▼                            ▼                            ▼
┌──────────────┐           ┌────────────────┐           ┌────────────────┐
│    REGIME    │           │   CORRELATION  │           │    ENSEMBLE    │
│BULL/BEAR/NEU │           │     MATRIX     │           │  (3 stratés)   │
│+ TRANSITION  │           │  (vraie div.)  │           │                │
└──────────────┘           └────────────────┘           └────────────────┘
       │                            │                            │
       └────────────┬───────────────┴────────────┬───────────────┘
                    ▼                            ▼
           ┌─────────────────┐           ┌──────────────────┐
           │ POSITION SIZING │           │   AUDIT TRAIL    │
           │ Kelly+Vol-Tgt   │           │  (tout trace)    │
           └─────────────────┘           └──────────────────┘
```

Voir [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) pour le détail complet.

---

## Stack

| Couche | Technologie | Contrainte |
|---|---|---|
| Langage | Python 3.10+ | Compatible Buildozer Android |
| UI / Mobile | Kivy 2.3.0 + KV Language | — |
| Build Android | Buildozer (API 33, arm64) | — |
| Données marché | Binance public klines + CoinGecko REST | Gratuit, sans clé |
| Exécution ordres | Binance API v3 (optionnel) | Chiffrement API keys PBKDF2 |
| Indicateurs | Pure Python | **0 dépendance** (pas NumPy) |
| Persistance | SQLite WAL | **9 tables** |
| Seules deps | `kivy>=2.3.0`, `requests>=2.31.0` | Minimal |

---

## Démarrage Rapide

### Desktop

```bash
cd MstreamTrader
pip install kivy>=2.3.0 requests>=2.31.0
python main.py
```

### Android (build APK)

```bash
pip install buildozer
buildozer android debug
```

### Activer le Bot Maître

1. Ouvrir l'application
2. Aller dans **⚙ Configuration**
3. Section **Bot Maître** → saisir le capital en USDT
4. Régler le risque par trade (défaut : 5 %)
5. Activer le switch **ACTIVER LE BOT MAÎTRE**
6. Le bot commence à analyser au prochain cycle (60 min)

### ⚠ Avant de trader en réel : VALIDER la stratégie

```bash
# 1. Tester sur 90 jours d'historique (backtest classique)
python run_backtest.py --days 90 --verbose

# 2. Optimiser les paramètres par grid search
python optimize_params.py --days 90 --regime --top 10

# 3. Valider la ROBUSTESSE hors-sample (walk-forward)
python optimize_params.py --days 120 --walk-forward --wf-window 30
```

Une stratégie est **déployable en réel** si son walk-forward retourne `ROBUSTE = OUI` (consistency > 60 %, Sharpe > 0.8, PF > 1.3).

---

## Cryptomonnaies Surveillées

| Coin | ID CoinGecko | Marché Binance |
|---|---|---|
| Bitcoin | `bitcoin` | `BTCUSDT` |
| Ethereum | `ethereum` | `ETHUSDT` |
| BNB | `binancecoin` | `BNBUSDT` |
| Solana | `solana` | `SOLUSDT` |
| XRP | `ripple` | `XRPUSDT` |
| Cardano | `cardano` | `ADAUSDT` |
| Dogecoin | `dogecoin` | `DOGEUSDT` |
| Polkadot | `polkadot` | `DOTUSDT` |

---

## État du projet

Voir [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md) pour le statut précis de chaque fonctionnalité (ce qui est codé, ce qui est intégré, ce qui est testé).

Pour l'audit sécurité des clés API, les précisions Binance dynamiques et le retry SQL atomique, voir [docs/INSTITUTIONAL.md](docs/INSTITUTIONAL.md).

---

## Documentation

| Document | Pour qui |
|---|---|
| [README.md](README.md) | Vue d'ensemble publique |
| [CLAUDE.md](CLAUDE.md) | Développeurs + Claude Code |
| [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md) | État réel code vs doc |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Architecture technique complète |
| [docs/BOT_MAITRE.md](docs/BOT_MAITRE.md) | Documentation du Bot Maître |
| [docs/INSTITUTIONAL.md](docs/INSTITUTIONAL.md) | Les 10 techniques niveau pro |
| [docs/REGIME.md](docs/REGIME.md) | Filtre de régime Bull/Bear |
| [docs/BACKTESTING.md](docs/BACKTESTING.md) | Backtesting et optimisation |

---

## Avertissement

> MstreamTrader est un outil d'aide au trading algorithmique. Le trading de cryptomonnaies comporte un risque élevé de perte en capital. Les performances passées ne préjugent pas des performances futures. Utilisez uniquement un capital que vous êtes prêt à perdre intégralement. Ce logiciel est fourni à titre éducatif et expérimental. Lancez toujours une validation backtest + walk-forward avant tout déploiement en argent réel.
