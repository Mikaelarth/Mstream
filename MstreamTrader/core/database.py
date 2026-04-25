"""
MstreamTrader - Base de données locale & Portfolio
Stockage SQLite : trades, positions, historique, config
"""

import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path

from core import paths


# Path centralisé : storage privé Android sur mobile, racine projet sur desktop.
# Le parent dir est créé si absent (cas premier lancement Android).
paths.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = str(paths.DB_FILE)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Crée les tables si elles n'existent pas."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS portfolio (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                coin_id    TEXT NOT NULL,
                symbol     TEXT NOT NULL,
                quantity   REAL NOT NULL DEFAULT 0,
                avg_buy    REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                coin_id     TEXT NOT NULL,
                symbol      TEXT NOT NULL,
                side        TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
                quantity    REAL NOT NULL,
                price       REAL NOT NULL,
                total_usdt  REAL NOT NULL,
                fee         REAL NOT NULL DEFAULT 0,
                source      TEXT NOT NULL DEFAULT 'MANUAL',
                note        TEXT,
                exchange_id TEXT,
                executed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS signals_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                coin_id    TEXT NOT NULL,
                symbol     TEXT NOT NULL,
                signal     TEXT NOT NULL,
                score      REAL NOT NULL,
                confidence REAL NOT NULL,
                price      REAL NOT NULL,
                stop_loss  REAL,
                take_profit REAL,
                risk_reward REAL,
                reasons    TEXT,
                logged_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS price_alerts (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                coin_id    TEXT NOT NULL,
                symbol     TEXT NOT NULL,
                condition  TEXT NOT NULL CHECK(condition IN ('ABOVE','BELOW')),
                target     REAL NOT NULL,
                triggered  INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS open_positions (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                portfolio_type TEXT NOT NULL,
                coin_id        TEXT NOT NULL,
                symbol         TEXT NOT NULL,
                entry_price    REAL NOT NULL,
                quantity       REAL NOT NULL,
                stop_loss      REAL NOT NULL,
                take_profit    REAL NOT NULL,
                entry_usdt     REAL NOT NULL,
                status         TEXT NOT NULL DEFAULT 'OPEN',
                opened_at      TEXT NOT NULL,
                closed_at      TEXT
            );

            CREATE TABLE IF NOT EXISTS auto_trader_log (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                portfolio_type TEXT NOT NULL,
                action         TEXT NOT NULL,
                coin_id        TEXT NOT NULL DEFAULT '',
                symbol         TEXT NOT NULL DEFAULT '',
                price          REAL NOT NULL DEFAULT 0,
                quantity       REAL NOT NULL DEFAULT 0,
                reason         TEXT NOT NULL DEFAULT '',
                logged_at      TEXT NOT NULL
            );
        """)

    # Paramètres par défaut
    default_settings = {
        "binance_api_key":       "",
        "binance_api_secret":    "",
        "usdt_balance":          "0.0",
        "risk_per_trade":        "2.0",
        "auto_trade":            "false",
        "theme":                 "dark",
        "currency":              "USD",
        "notifications":         "true",
        # Bot Maître
        "auto_trade_master":     "false",
        "budget_master":         "0.0",
        "budget_master_initial": "0.0",   # capital initial — ne change jamais (pour ROI)
        "risk_master":           "5.0",
        # Mode Paper Trading (ledger séparé, zero risque)
        "paper_mode":                   "false",
        "budget_master_paper":          "0.0",
        "budget_master_initial_paper":  "0.0",
        # Notifications Telegram (tokens chiffrés via crypto.py)
        "telegram_bot_token":           "",
        "telegram_chat_id":             "",
        # Portefeuille Sécurité (legacy)
        "auto_trade_securite":   "false",
        "budget_securite":       "0.0",
        # Portefeuille Libre (legacy)
        "auto_trade_libre":      "false",
        "budget_libre":          "0.0",
        "risk_libre":            "3.0",
    }
    with get_connection() as conn:
        for k, v in default_settings.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (k, v)
            )

    # Migration : chiffrer les clés API stockées en clair (héritage ancienne version)
    _migrate_encrypt_api_keys()

    # Créer la table audit_log (institutional grade)
    try:
        from core.audit import init_audit_table
        init_audit_table()
    except ImportError:
        pass   # audit est optionnel au démarrage

    # Créer les tables du module adaptive (apprentissage en ligne)
    try:
        from core.adaptive import init_adaptive_tables
        init_adaptive_tables()
    except ImportError:
        pass   # adaptive est optionnel au démarrage

    # Migration : ajouter les colonnes strategy_votes_json + profile_name à
    # open_positions si elles n'existent pas (requis pour l'attribution correcte
    # par l'agent adaptatif).
    _migrate_open_positions_adaptive()

    # Equity history (V14 — graph d'équité dans l'UI)
    try:
        from core.equity_history import init_equity_table
        init_equity_table()
    except ImportError:
        pass


def _migrate_open_positions_adaptive():
    """
    Migration idempotente de open_positions :
    - strategy_votes_json + profile_name (V9 — attribution adaptive)
    - tp1_taken (V12 — partial exits)
    - tp1_price (V12 — prix du Take-Profit partiel calculé à l'entrée)
    """
    with get_connection() as conn:
        cols = conn.execute("PRAGMA table_info(open_positions)").fetchall()
        col_names = {c[1] for c in cols}
        if "strategy_votes_json" not in col_names:
            conn.execute("ALTER TABLE open_positions ADD COLUMN strategy_votes_json TEXT")
        if "profile_name" not in col_names:
            conn.execute("ALTER TABLE open_positions ADD COLUMN profile_name TEXT")
        if "tp1_taken" not in col_names:
            conn.execute("ALTER TABLE open_positions ADD COLUMN tp1_taken INTEGER DEFAULT 0")
        if "tp1_price" not in col_names:
            conn.execute("ALTER TABLE open_positions ADD COLUMN tp1_price REAL")


def _migrate_encrypt_api_keys():
    """Chiffre les clés API Binance si elles sont encore en clair."""
    from core.crypto import encrypt, is_encrypted
    for key in ("binance_api_key", "binance_api_secret"):
        value = get_setting(key, "")
        if value and not is_encrypted(value):
            set_setting(key, encrypt(value))


# ─── Settings ────────────────────────────────────────────────────────────────

def get_setting(key: str, default: str = "") -> str:
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value))
        )


def increment_numeric_setting(key: str, delta: float, default: float = 0.0,
                               max_retries: int = 5) -> float:
    """
    Incrémente atomiquement une valeur numérique stockée en settings.
    Thread-safe via transaction SQLite + retry exponentiel sur SQLITE_BUSY.

    Usage : ajout/retrait de P&L au budget d'un portefeuille.
    """
    import time as _time
    last_exc = None
    for attempt in range(max_retries):
        try:
            with get_connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT value FROM settings WHERE key=?", (key,)
                ).fetchone()
                current = float(row["value"]) if row else default
                new_value = round(current + delta, 4)
                conn.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (key, str(new_value))
                )
                conn.commit()
                return new_value
        except sqlite3.OperationalError as exc:
            last_exc = exc
            msg = str(exc).lower()
            if ("locked" in msg or "busy" in msg) and attempt < max_retries - 1:
                # Backoff exponentiel : 50ms, 100ms, 200ms, 400ms, 800ms
                _time.sleep(0.05 * (2 ** attempt))
                continue
            raise
    if last_exc:
        raise last_exc
    return default


def get_setting_encrypted(key: str, default: str = "") -> str:
    """Lit un setting et déchiffre automatiquement si nécessaire."""
    from core.crypto import decrypt
    raw = get_setting(key, default)
    return decrypt(raw) if raw else default


def set_setting_encrypted(key: str, value: str):
    """Sauve un setting en le chiffrant si la valeur n'est pas vide."""
    from core.crypto import encrypt
    enc = encrypt(value) if value else ""
    set_setting(key, enc)


# ─── Portfolio ────────────────────────────────────────────────────────────────

def get_portfolio() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM portfolio WHERE quantity > 0 ORDER BY avg_buy DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def update_position(coin_id: str, symbol: str, quantity_delta: float, price: float, side: str):
    """Met à jour la position d'un actif après un trade."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM portfolio WHERE coin_id=?", (coin_id,)
        ).fetchone()

        now = datetime.now().isoformat()

        if side == "BUY":
            if row:
                old_qty   = row["quantity"]
                old_avg   = row["avg_buy"]
                new_qty   = old_qty + quantity_delta
                new_avg   = ((old_qty * old_avg) + (quantity_delta * price)) / new_qty
                conn.execute(
                    "UPDATE portfolio SET quantity=?, avg_buy=? WHERE coin_id=?",
                    (new_qty, new_avg, coin_id)
                )
            else:
                conn.execute(
                    "INSERT INTO portfolio (coin_id, symbol, quantity, avg_buy, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (coin_id, symbol, quantity_delta, price, now)
                )
        elif side == "SELL":
            if row:
                new_qty = max(0, row["quantity"] - quantity_delta)
                conn.execute(
                    "UPDATE portfolio SET quantity=? WHERE coin_id=?",
                    (new_qty, coin_id)
                )


def calculate_portfolio_value(prices: dict) -> dict:
    """Calcule la valeur totale du portefeuille avec PnL."""
    positions = get_portfolio()
    total_invested = 0.0
    total_current  = 0.0
    result = []

    for pos in positions:
        cid   = pos["coin_id"]
        qty   = pos["quantity"]
        avg   = pos["avg_buy"]
        price = prices.get(cid, {}).get("price", avg)

        invested = qty * avg
        current  = qty * price
        pnl      = current - invested
        pnl_pct  = (pnl / invested * 100) if invested > 0 else 0

        total_invested += invested
        total_current  += current

        result.append({
            **pos,
            "current_price": price,
            "invested":      round(invested, 2),
            "current_value": round(current, 2),
            "pnl":           round(pnl, 2),
            "pnl_pct":       round(pnl_pct, 2),
        })

    total_pnl = total_current - total_invested
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0

    return {
        "positions":     result,
        "total_invested": round(total_invested, 2),
        "total_value":   round(total_current, 2),
        "total_pnl":     round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
    }


# ─── Trades ──────────────────────────────────────────────────────────────────

def record_trade(
    coin_id: str,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    fee: float = 0.0,
    source: str = "MANUAL",
    note: str = "",
    exchange_id: str = "",
):
    """Enregistre un trade et met à jour la position."""
    total_usdt = quantity * price
    now = datetime.now().isoformat()

    with get_connection() as conn:
        conn.execute(
            """INSERT INTO trades
               (coin_id, symbol, side, quantity, price, total_usdt, fee, source, note, exchange_id, executed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (coin_id, symbol, side, quantity, price, total_usdt, fee, source, note, exchange_id, now)
        )

    update_position(coin_id, symbol, quantity, price, side)

    # Mettre à jour le solde USDT
    balance = float(get_setting("usdt_balance", "0"))
    if side == "BUY":
        balance -= (total_usdt + fee)
    else:
        balance += (total_usdt - fee)
    set_setting("usdt_balance", str(round(balance, 4)))


def get_trades(coin_id: str | None = None, limit: int = 100) -> list[dict]:
    with get_connection() as conn:
        if coin_id:
            rows = conn.execute(
                "SELECT * FROM trades WHERE coin_id=? ORDER BY executed_at DESC LIMIT ?",
                (coin_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY executed_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def get_trade_stats() -> dict:
    """Statistiques globales des trades."""
    with get_connection() as conn:
        trades = conn.execute("SELECT * FROM trades").fetchall()

    if not trades:
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0, "total_pnl": 0}

    # Calcul simplifié par coin
    coin_buys  = {}
    total_pnl  = 0
    wins = losses = 0

    for t in trades:
        t = dict(t)
        cid = t["coin_id"]
        if t["side"] == "BUY":
            if cid not in coin_buys:
                coin_buys[cid] = {"qty": 0, "avg": 0}
            old_qty = coin_buys[cid]["qty"]
            new_qty = old_qty + t["quantity"]
            coin_buys[cid]["avg"] = (
                (old_qty * coin_buys[cid]["avg"] + t["quantity"] * t["price"]) / new_qty
                if new_qty > 0 else t["price"]
            )
            coin_buys[cid]["qty"] = new_qty
        elif t["side"] == "SELL" and cid in coin_buys:
            buy_avg = coin_buys[cid]["avg"]
            pnl = (t["price"] - buy_avg) * t["quantity"] - t["fee"]
            total_pnl += pnl
            if pnl > 0:
                wins += 1
            else:
                losses += 1

    total_closed = wins + losses
    win_rate = (wins / total_closed * 100) if total_closed > 0 else 0

    return {
        "total":     len(trades),
        "wins":      wins,
        "losses":    losses,
        "win_rate":  round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
    }


# ─── Signaux Log ─────────────────────────────────────────────────────────────

def log_signal(signal_obj) -> None:
    """Sauvegarde un signal analysé en base."""
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO signals_log
               (coin_id, symbol, signal, score, confidence, price,
                stop_loss, take_profit, risk_reward, reasons, logged_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal_obj.coin_id,
                signal_obj.symbol,
                signal_obj.signal.value,
                signal_obj.score,
                signal_obj.confidence,
                signal_obj.price,
                signal_obj.stop_loss,
                signal_obj.take_profit,
                signal_obj.risk_reward,
                json.dumps(signal_obj.reasons),
                datetime.now().isoformat(),
            )
        )


def get_signals_history(limit: int = 50) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM signals_log ORDER BY logged_at DESC LIMIT ?", (limit,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["reasons"] = json.loads(d["reasons"] or "[]")
            result.append(d)
        return result


# ─── Alertes Prix ─────────────────────────────────────────────────────────────

def add_price_alert(coin_id: str, symbol: str, condition: str, target: float):
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO price_alerts (coin_id, symbol, condition, target, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (coin_id, symbol, condition.upper(), target, datetime.now().isoformat())
        )


def check_alerts(prices: dict) -> list[dict]:
    """Vérifie les alertes et retourne celles déclenchées."""
    triggered = []
    with get_connection() as conn:
        alerts = conn.execute(
            "SELECT * FROM price_alerts WHERE triggered=0"
        ).fetchall()

        for alert in alerts:
            a = dict(alert)
            cid   = a["coin_id"]
            price = prices.get(cid, {}).get("price", 0)
            hit   = False

            if a["condition"] == "ABOVE" and price >= a["target"]:
                hit = True
            elif a["condition"] == "BELOW" and price <= a["target"]:
                hit = True

            if hit:
                conn.execute(
                    "UPDATE price_alerts SET triggered=1 WHERE id=?", (a["id"],)
                )
                triggered.append({**a, "current_price": price})

    return triggered


# ─── Auto-Trader : Positions Ouvertes ────────────────────────────────────────

def get_open_positions(portfolio_type: str) -> list[dict]:
    """Retourne les positions ouvertes d'un portefeuille."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM open_positions WHERE portfolio_type=? AND status='OPEN' "
            "ORDER BY opened_at DESC",
            (portfolio_type,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_open_positions() -> list[dict]:
    """Toutes les positions ouvertes tous portefeuilles confondus."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM open_positions WHERE status='OPEN' ORDER BY opened_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def open_auto_position(
    portfolio_type: str,
    coin_id: str,
    symbol: str,
    entry_price: float,
    quantity: float,
    stop_loss: float,
    take_profit: float,
    entry_usdt: float,
    strategy_votes: dict | None = None,
    profile_name: str | None = None,
):
    """
    Enregistre l'ouverture d'une position automatique.

    `strategy_votes` : dict {strategy_name: bool_voted_buy} — permet à l'agent
    adaptatif d'attribuer le crédit des wins/losses aux bonnes stratégies.
    `profile_name`   : nom du profil paramétrique utilisé à l'entrée — permet
    au ParameterTuner d'accumuler des stats par profil réel.
    """
    votes_json = json.dumps(strategy_votes) if strategy_votes else None
    # Partial exit TP1 : à mi-chemin entre entry et take_profit (≈ 1.5R)
    tp1_price = entry_price + (take_profit - entry_price) * 0.5 if take_profit > entry_price else None
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO open_positions
               (portfolio_type, coin_id, symbol, entry_price, quantity,
                stop_loss, take_profit, entry_usdt, status, opened_at,
                strategy_votes_json, profile_name, tp1_price, tp1_taken)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, 0)""",
            (portfolio_type, coin_id, symbol, entry_price, quantity,
             stop_loss, take_profit, entry_usdt, datetime.now().isoformat(),
             votes_json, profile_name, tp1_price)
        )


def update_position_after_partial_exit(position_id: int,
                                         new_quantity: float,
                                         new_stop_loss: float) -> None:
    """
    Appelé après un Partial Exit (TP1 atteint) :
      - Quantité restante diminuée (ex : 50 % vendu, 50 % conservé)
      - Stop-Loss remonté (souvent au break-even pour sécuriser le reste)
      - tp1_taken = 1 pour ne pas refaire le partial
    """
    with get_connection() as conn:
        conn.execute(
            """UPDATE open_positions
               SET quantity=?, stop_loss=?, tp1_taken=1
               WHERE id=? AND status='OPEN'""",
            (new_quantity, new_stop_loss, position_id)
        )


def close_open_position(position_id: int, status: str):
    """Ferme une position (status: EXIT_TP, EXIT_SL, CLOSED_MANUAL)."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE open_positions SET status=?, closed_at=? WHERE id=?",
            (status, datetime.now().isoformat(), position_id)
        )


def update_position_sl(position_id: int, new_sl: float):
    """Met à jour le stop-loss d'une position ouverte (trailing SL)."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE open_positions SET stop_loss=? WHERE id=? AND status='OPEN'",
            (new_sl, position_id)
        )


def is_in_cooldown(portfolio_type: str, coin_id: str, hours: int) -> bool:
    """
    Vérifie si un coin est en période de cooldown dans un portefeuille donné.
    (= un trade d'entrée AUTO sur ce coin a eu lieu dans les <hours> dernières heures)
    """
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    source_prefix = f"AUTO_ENTRY_{portfolio_type.upper()}"
    with get_connection() as conn:
        row = conn.execute(
            """SELECT id FROM trades
               WHERE coin_id=? AND source=? AND executed_at >= ?
               LIMIT 1""",
            (coin_id, source_prefix, cutoff)
        ).fetchone()
    return row is not None


def get_auto_portfolio_summary(portfolio_type: str, prices: dict) -> dict:
    """
    Calcule le résumé d'un portefeuille automatique :
    budget alloué, montant investi, valeur courante, P&L ouvert + réalisé.
    """
    budget_key = f"budget_{portfolio_type}"
    budget     = float(get_setting(budget_key, "0"))

    open_pos   = get_open_positions(portfolio_type)
    invested   = sum(p["entry_usdt"] for p in open_pos)
    current_v  = sum(
        p["quantity"] * prices.get(p["coin_id"], {}).get("price", p["entry_price"])
        for p in open_pos
    )
    unrealized_pnl = current_v - invested

    # P&L réalisé sur les trades fermés de ce portefeuille
    # Inclut les EXIT (TP/SL final) ET les PARTIAL (TP1) — sinon le pnl réalisé
    # serait sous-évalué quand le bot prend des partial exits.
    source_entry = f"AUTO_ENTRY_{portfolio_type.upper()}"
    with get_connection() as conn:
        buys = conn.execute(
            "SELECT * FROM trades WHERE source=? AND side='BUY'",
            (source_entry,)
        ).fetchall()
        sells = conn.execute(
            "SELECT * FROM trades WHERE side='SELL' AND "
            "(source LIKE ? OR source = ?)",
            (f"AUTO_EXIT_%_{portfolio_type.upper()}",
             f"AUTO_PARTIAL_{portfolio_type.upper()}")
        ).fetchall()

    realized_pnl = sum(float(dict(s)["total_usdt"]) - float(dict(s)["fee"])
                       for s in sells) - \
                   sum(float(dict(b)["total_usdt"]) + float(dict(b)["fee"])
                       for b in buys
                       if dict(b)["coin_id"] not in {p["coin_id"] for p in open_pos})

    return {
        "budget":          round(budget, 2),
        "invested":        round(invested, 2),
        "current_value":   round(current_v, 2),
        "unrealized_pnl":  round(unrealized_pnl, 2),
        "realized_pnl":    round(realized_pnl, 2),
        "open_count":      len(open_pos),
        "open_positions":  [
            {
                **p,
                "current_price": prices.get(p["coin_id"], {}).get("price", p["entry_price"]),
                "unrealized_pnl": round(
                    (prices.get(p["coin_id"], {}).get("price", p["entry_price"]) - p["entry_price"])
                    * p["quantity"], 2
                ),
            }
            for p in open_pos
        ],
    }


# ─── Auto-Trader : Journal ────────────────────────────────────────────────────

def log_auto_trader(
    portfolio_type: str,
    action: str,
    coin_id: str,
    symbol: str,
    price: float,
    quantity: float,
    reason: str,
):
    """Enregistre une action du moteur de trading automatique."""
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO auto_trader_log
               (portfolio_type, action, coin_id, symbol, price, quantity, reason, logged_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (portfolio_type, action, coin_id, symbol,
             price, quantity, reason, datetime.now().isoformat())
        )


def get_auto_trader_logs(portfolio_type: str | None = None, limit: int = 50) -> list[dict]:
    """Retourne les dernières actions du moteur automatique."""
    with get_connection() as conn:
        if portfolio_type:
            rows = conn.execute(
                "SELECT * FROM auto_trader_log WHERE portfolio_type=? "
                "ORDER BY logged_at DESC LIMIT ?",
                (portfolio_type, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM auto_trader_log ORDER BY logged_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
    return [dict(r) for r in rows]
