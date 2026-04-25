"""
MstreamTrader - Mode Paper Trading
====================================

Bascule run-time entre mode réel (clés Binance) et mode paper trading (simulation).

Architecture :
  - Un flag `paper_mode` dans settings DB
  - Un préfixe `PAPER_` pour toutes les sources de trades en mode paper
  - Un suffixe `_PAPER` pour les portfolio_types ('master_paper', etc.)
  - Ledger séparé : les trades paper n'affectent pas les stats réelles

Les données partagent la MÊME DB (pas de fichier séparé) pour simplicité de
backup/migration, mais les entrées sont taguées pour être filtrables.

Usage typique :
  1. User active paper_mode via Settings → `paper_mode = true`
  2. Tous les nouveaux trades sont marqués PAPER, budget_master_paper utilisé
  3. Le ROI paper ne contamine pas le ROI réel
  4. Statistiques paper filtrables via `get_paper_stats()`

Bénéfices :
  - Test safe 2 semaines avant argent réel
  - Valider l'agent adaptatif sans perte possible
  - Backtest en live (les trades réels du marché, mais sans argent)
"""

import logging


logger = logging.getLogger("paper_mode")


def is_paper_mode() -> bool:
    """Retourne True si le mode paper trading est actif."""
    from core.database import get_setting
    return get_setting("paper_mode", "false") == "true"


def set_paper_mode(enabled: bool) -> None:
    """Active / désactive le mode paper. Persistant en DB."""
    from core.database import set_setting
    set_setting("paper_mode", "true" if enabled else "false")
    logger.info(f"[PaperMode] {'ACTIVE' if enabled else 'DESACTIVE'}")


def get_portfolio_type(base_type: str = "master") -> str:
    """
    Retourne le portfolio_type à utiliser selon le mode.
    En paper : "master" → "master_paper" (tables séparées).
    En réel  : inchangé.
    """
    if is_paper_mode():
        return f"{base_type}_paper"
    return base_type


def get_source_prefix(action: str, portfolio_type: str) -> str:
    """
    Retourne la source à utiliser pour `trades.source`.
    En paper, préfixe PAPER_ pour filtrage ultérieur.
    """
    prefix = "PAPER_" if is_paper_mode() else ""
    return f"{prefix}AUTO_{action.upper()}_{portfolio_type.upper()}"


def get_budget_key() -> str:
    """
    Retourne la clé settings pour le budget courant.
    En paper : budget_master_paper (séparé du réel).
    En réel  : budget_master.
    """
    return "budget_master_paper" if is_paper_mode() else "budget_master"


def get_initial_key() -> str:
    """Clé du capital initial pour le ROI (séparé en paper)."""
    return "budget_master_initial_paper" if is_paper_mode() else "budget_master_initial"


def get_paper_stats() -> dict:
    """
    Statistiques du mode paper : budget, trades, ROI.
    Utile pour UI / comparaison avec le mode réel.
    """
    from core.database import get_setting, get_connection

    budget_current = float(get_setting("budget_master_paper", "0"))
    budget_initial = float(get_setting("budget_master_initial_paper", "0"))
    roi = ((budget_current - budget_initial) / budget_initial * 100
           if budget_initial > 0 else 0.0)

    with get_connection() as conn:
        trades_count = conn.execute(
            "SELECT COUNT(*) FROM trades WHERE source LIKE 'PAPER_AUTO_%'"
        ).fetchone()[0]
        open_count = conn.execute(
            "SELECT COUNT(*) FROM open_positions "
            "WHERE portfolio_type LIKE '%_paper' AND status='OPEN'"
        ).fetchone()[0]

    return {
        "active":          is_paper_mode(),
        "budget_current":  round(budget_current, 2),
        "budget_initial":  round(budget_initial, 2),
        "roi_pct":         round(roi, 2),
        "trades_count":    trades_count,
        "open_positions":  open_count,
    }


def init_paper_budget(initial_amount: float) -> None:
    """Initialise le budget paper (appelé au premier démarrage du mode)."""
    from core.database import set_setting
    set_setting("budget_master_paper", str(initial_amount))
    set_setting("budget_master_initial_paper", str(initial_amount))
    logger.info(f"[PaperMode] Budget initial : ${initial_amount:,.2f}")
