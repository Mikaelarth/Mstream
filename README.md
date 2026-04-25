# MstreamTrader

> **Bot de trading crypto autonome (BETA), open-source, mobile-first.**
>
> 28 modules Python, ~12 550 lignes (avec tests), zéro dépendance lourde.
> 311 tests pytest, CI/CD GitHub Actions (tests + APK auto à chaque push).
>
> Statut : **fonctionnel mais non encore validé en production** — voir
> section [Statut honnête](#statut-honnête) avant tout usage.

---

## L'idée

Les marchés crypto tournent 24h/24, mais le trader humain non.
La peur, la cupidité et la fatigue sabotent systématiquement les
décisions. MstreamTrader confie le capital à un algorithme discipliné,
disponible en permanence, et **dont chaque décision est traçable**
(audit trail JSON complet).

Question précise du projet :

> Peut-on confier un capital à un bot mobile et le laisser le faire
> croître seul, avec la même rigueur qu'un fonds quantitatif, sans
> abonnement cloud et sans dépendance à une API payante ?

**Réponse à ce stade : la mécanique est en place, le edge mathématique
n'est pas encore prouvé sur historique long.** On y travaille.

---

## Avantages compétitifs visés

Vs. 3Commas / Cryptohopper / Pionex / Trality / Bitsgap :

| Axe | MstreamTrader |
|---|---|
| **Open-source** | Code lisible, auditable, modifiable |
| **100 % local** | Aucune donnée sortante, pas de cloud, pas d'abonnement |
| **Régime-aware natif** | Bull/Bear/Neutral pondère tous les paramètres dynamiquement |
| **Kelly Fractional + Volatility Targeting** | Position sizing institutionnel |
| **Audit trail JSON complet** | Chaque décision (entry, exit, skip) est traçable et queryable |
| **Walk-Forward intégré** | Validation prospective contre l'overfitting |
| **Adaptive learning** | Thompson Sampling sur les stratégies (apprend de chaque trade) |
| **Circuit Breaker 4 niveaux** | Pause auto sur série de SL ou drawdown anormal |
| **Mobile + Desktop** | Même code, deux plateformes |

Aucun de ces 9 axes n'est aspirationnel : tous sont **codés et testés
unitairement**. Mais leur **valeur économique** (combien d'euros gagnés
en plus que la concurrence) reste à mesurer empiriquement.

---

## Statut honnête

| Dimension | État | Preuve |
|---|:-:|---|
| Code architecture | ✅ Fait | 28 modules, 311 tests verts |
| App desktop fonctionne | ✅ Validé | Lancé en runtime Windows |
| APK Android s'installe et tourne | ✅ Validé | Buildozer CI ; tests utilisateur sur smartphone |
| Persistance DB Android | ⚠️ Code en place | `core/paths.py` détecte storage privé Android. Test runtime user à confirmer |
| Connexion Binance | ⚠️ Code en place | SSL_CTX appliqué. Diagnostic 2 étapes (ping + account). À valider runtime user |
| Backtest produit des trades | ✅ Validé | 6 trades sur 60-166j BTC/ETH/SOL |
| **Sharpe > 1.0 sur 1 an OOS** | 🔴 **Non atteint** | Sharpe -0.96 sur 166j 4h actuel — calibration en cours |
| **Profit Factor > 1.3** | 🔴 **Non atteint** | PF 0.14 actuel |
| Max Drawdown < 20 % | ✅ | 0.12 % actuel (mais peu de trades) |
| Tests pytest | ✅ | 311/311 verts |
| CI Tests + Build APK | ✅ | GitHub Actions |
| Audit trail JSON queryable | ✅ | 30 jours de rétention |
| Backup DB + restore atomique | ✅ | `restore_from_backup` avec rollback |
| Paper mode 30j prouvé | 🔴 | À lancer |
| Clés API en Android KeyStore | 🔴 | Actuellement PBKDF2 + XOR (obfuscation, pas KeyStore) |
| Notifications Telegram | ✅ Code | À valider runtime user |

**Conclusion** : la base est solide, le moteur tourne, mais **la
preuve de l'edge** (Sharpe, profit factor sur 1 an out-of-sample) reste
à fournir. **Ne déployez pas de capital réel tant que cette preuve n'est
pas faite.**

---

## Démarrage rapide

### Desktop (Windows / Linux / Mac)

```bash
# Python 3.11 ou 3.12 recommandé (Kivy ne supporte pas encore 3.14)
git clone https://github.com/Mikaelarth/Mstream.git
cd Mstream/MstreamTrader
pip install kivy>=2.3.0 requests>=2.31.0
python main.py
```

### APK Android

L'APK debug est **buildé automatiquement** par GitHub Actions à chaque
push sur `main`. Pour récupérer la dernière version :

1. Va sur https://github.com/Mikaelarth/Mstream/actions
2. Clique sur le dernier run vert "Build Android APK"
3. Télécharge l'artifact `mstreamtrader-debug-apk` (ZIP de ~35 MB)
4. Dézippe → `mstreamtrader-X.Y.Z-arm64-v8a-debug.apk`
5. Transfère sur ton téléphone, installe (autoriser sources inconnues)

Pour builder localement (Linux ou WSL2 uniquement, pas Windows natif) :

```bash
pip install buildozer cython==0.29.36
# Dans MstreamTrader/
buildozer android debug
# → bin/mstreamtrader-1.0.0-arm64-v8a-debug.apk
```

### Activer le Bot Maître

1. Lance l'app
2. Va dans **Configuration**
3. Section **Bot Maître** → entre un capital en USDT (ex: 1000) → **Allouer**
4. Règle le risque par trade (défaut 5 %)
5. **Activer le switch** ACTIVER LE BOT MAÎTRE
6. Le bot lance son premier cycle après ~60 secondes

**Recommandation** : commence par activer **Paper Trading mode** (section
juste en dessous) pour faire tourner le bot 1-2 semaines en virtuel avant
d'investir du vrai capital.

---

## Mode Paper Trading (simulation)

Mstream contient un mode **paper** isolé qui :
- Simule les ordres sans toucher à Binance réel
- Utilise un ledger séparé (clés DB `_paper`)
- Affiche le ROI virtuel + statistiques
- Permet de valider la stratégie sur ton flux de marché live, pendant
  la durée que tu veux, avant de confier de l'argent réel

C'est la voie recommandée tant que les critères de Sharpe / PF /
walk-forward ne sont pas validés en backtest profond.

---

## Validation rigoureuse avant capital réel

```bash
cd MstreamTrader

# 1. Backtest classique sur 90 jours
python run_backtest.py --days 90 --verbose

# 2. Grid search d'optimisation (~80 combinaisons, ~5 min)
python optimize_params.py --days 90 --top 10

# 3. Walk-Forward (validation prospective hors-sample)
python optimize_params.py --days 120 --walk-forward --wf-window 30
```

**Critères pour considérer la stratégie déployable** :

- Walk-forward retourne `is_robust = True` (consistency > 60 %, Sharpe avg > 0.5, PF avg > 1.2)
- Sharpe annualisé sur 1 an out-of-sample > 1.0
- Profit Factor > 1.3
- Max Drawdown < 20 %
- Au moins 30 trades par an (assez de data pour statistique fiable)

**Si un seul critère manque, ne pas déployer en réel.**

---

## Architecture (résumé)

```
                  ┌────────────────────────────────────────┐
                  │            CIRCUIT BREAKER             │
                  │         (kill switch 4 niveaux)        │
                  └────────────────┬───────────────────────┘
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
│BULL/BEAR/NEU │           │     MATRIX     │           │  (3 strats)    │
│+ TRANSITION  │           │  (vraie div.)  │           │                │
└──────────────┘           └────────────────┘           └────────────────┘
       │                            │                            │
       └────────────┬───────────────┴────────────┬───────────────┘
                    ▼                            ▼
           ┌─────────────────┐           ┌──────────────────┐
           │ POSITION SIZING │           │   AUDIT TRAIL    │
           │ Kelly+Vol-Tgt   │           │  (tout tracé)    │
           └─────────────────┘           └──────────────────┘
```

Détails complets : [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Stack

| Couche | Technologie | Note |
|---|---|---|
| Langage | Python 3.11 / 3.12 | (3.14 non supporté par Kivy à ce jour) |
| UI / Mobile | Kivy 2.3.1 + KV Language | Buildozer pour Android |
| Build Android | Buildozer (API 33, arm64-v8a + armeabi-v7a) | CI GitHub Actions |
| Données marché | Binance public klines + CoinGecko REST | Gratuit, sans clé |
| Exécution ordres | Binance API v3 (optionnel) | Clés chiffrées PBKDF2-SHA256 |
| Indicateurs | Pure Python | **0 dépendance** scientifique |
| Persistance | SQLite WAL | 14 tables (settings, trades, audit_log, equity_history, etc.) |
| HTTPS / SSL | `core/net.py` centralisé | certifi + system CAs Android |
| Deps | `kivy>=2.3.0`, `requests>=2.31.0` (+ `certifi`, `openssl` sur Android) | Minimal |

---

## Cryptomonnaies surveillées

| Coin | ID CoinGecko | Symbole Binance |
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

## Documentation

| Document | Pour qui |
|---|---|
| [README.md](README.md) | Vue d'ensemble publique (ce fichier) |
| [CLAUDE.md](CLAUDE.md) | Développeurs + agents IA |
| [docs/MISSION_PROMPT.md](docs/MISSION_PROMPT.md) | Cadre des itérations rigoureuses |
| [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md) | État réel code vs doc |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Architecture technique complète |
| [docs/BOT_MAITRE.md](docs/BOT_MAITRE.md) | Documentation Bot Maître |
| [docs/INSTITUTIONAL.md](docs/INSTITUTIONAL.md) | Les 10 techniques institutionnelles |
| [docs/REGIME.md](docs/REGIME.md) | Filtre de régime Bull/Bear |
| [docs/BACKTESTING.md](docs/BACKTESTING.md) | Backtesting et walk-forward |

---

## Tests & qualité

```bash
cd MstreamTrader
pip install pytest
python -m pytest tests/ -q
# → 311 passed
```

Densité de tests : ~2.5 % (311 tests / 12 550 lignes), au-dessus du
standard industrie pour Python.

CI continue : https://github.com/Mikaelarth/Mstream/actions

---

## Avertissement

> **MstreamTrader est en BETA.** Le trading de cryptomonnaies comporte un
> risque élevé de perte en capital. Les performances passées ne préjugent
> pas des performances futures. **Le edge de la stratégie n'est pas
> encore prouvé sur 1 an out-of-sample.** N'utilisez JAMAIS un capital
> que vous n'êtes pas prêt à perdre intégralement.
>
> Ce logiciel est fourni à titre éducatif et expérimental, sans aucune
> garantie. L'auteur et les contributeurs ne sont pas responsables des
> pertes financières subies par son utilisation.
>
> **Avant tout déploiement en argent réel** :
>
> 1. Lance une validation backtest + walk-forward complète
> 2. Vérifie que tous les critères de la section "Validation rigoureuse"
>    sont atteints
> 3. Lance le bot 30 jours minimum en mode Paper Trading
> 4. Démarre avec un capital symbolique (50-100 USDT) pour valider en réel
> 5. N'augmente le capital que progressivement après preuve de constance

---

## Licence

Open-source. Voir le repo pour la licence exacte.

## Contribution

Issues et PRs bienvenus sur https://github.com/Mikaelarth/Mstream
