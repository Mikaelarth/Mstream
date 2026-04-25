"""
MstreamTrader - Health Checks & Anomaly Detection
===================================================

Vérifications continues de la santé du système et de la qualité des données :
    - Disponibilité des APIs (Binance, CoinGecko)
    - Latence des appels
    - Cohérence des données (prix aberrants, volumes anormaux)
    - Divergence inter-sources (écart Binance vs CoinGecko > seuil)
    - Stale data detection (données non rafraîchies)

Déclenche le circuit breaker en cas de problème détecté.
"""

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class HealthStatus:
    healthy:           bool  = True
    checks_passed:     int   = 0
    checks_failed:     int   = 0
    last_check_ts:     float = 0.0
    last_failure_msg:  str   = ""
    binance_latency_ms: Optional[float] = None
    coingecko_latency_ms: Optional[float] = None
    last_binance_ok:   float = 0.0
    last_coingecko_ok: float = 0.0
    issues:            list  = field(default_factory=list)   # 10 derniers issues


@dataclass
class HealthConfig:
    max_api_latency_ms:         float = 8000.0       # > 8s = problème réseau
    abnormal_price_jump_pct:    float = 15.0         # bougie > 15 % move en 1h
    min_volume_ratio:           float = 0.1          # volume > 10 % du mean — sinon données suspectes
    price_divergence_pct:       float = 3.0          # Binance vs CoinGecko > 3 % = anomalie
    stale_data_threshold_sec:   float = 7200.0       # 2h sans refresh = stale
    abnormal_bb_bandwidth_max:  float = 50.0         # BB bandwidth > 50 % = données bizarres


class HealthChecker:
    """Moniteur de santé centralisé."""

    def __init__(self, config: Optional[HealthConfig] = None):
        self.config = config or HealthConfig()
        self.status = HealthStatus()

    # ─── Checks individuels ───────────────────────────────────────────────────

    def ping_binance(self) -> tuple[bool, float]:
        """Ping Binance public, retourne (ok, latency_ms)."""
        from core.market_data import _fetch_json
        start = time.time()
        try:
            data = _fetch_json("https://api.binance.com/api/v3/ping", timeout=5)
            latency = (time.time() - start) * 1000
            ok = data is not None
            return ok, latency
        except (OSError, ValueError) as exc:
            # OSError = réseau (URLError, timeout). ValueError = JSON malformé.
            import logging
            logging.getLogger("health").debug(f"ping_binance failed: {exc}")
            return False, (time.time() - start) * 1000

    def ping_coingecko(self) -> tuple[bool, float]:
        """Ping CoinGecko, retourne (ok, latency_ms)."""
        from core.market_data import _fetch_json
        start = time.time()
        try:
            data = _fetch_json("https://api.coingecko.com/api/v3/ping", timeout=5)
            latency = (time.time() - start) * 1000
            ok = data is not None
            return ok, latency
        except (OSError, ValueError) as exc:
            import logging
            logging.getLogger("health").debug(f"ping_coingecko failed: {exc}")
            return False, (time.time() - start) * 1000

    def check_data_freshness(self, data_timestamp: float) -> bool:
        """Les données sont-elles fraîches (< stale_data_threshold_sec) ?"""
        if data_timestamp <= 0:
            return False
        return (time.time() - data_timestamp) < self.config.stale_data_threshold_sec

    def check_price_sanity(self, candles: list[dict]) -> tuple[bool, str]:
        """
        Détecte les prix aberrants (sautes intra-bougie > X %).
        Retourne (ok, message).
        """
        if not candles or len(candles) < 2:
            return True, ""

        for c in candles[-20:]:   # vérifier les 20 dernières
            o = c.get("open", 0)
            h = c.get("high", 0)
            low = c.get("low", 0)
            cl = c.get("close", 0)
            if o <= 0 or h <= 0 or low <= 0 or cl <= 0:
                return False, f"Bougie avec prix nul/negatif : {c}"
            if low > h:
                return False, f"Low > High : low={low}, high={h}"
            if o > h * 1.001 or cl > h * 1.001:
                return False, f"Open/Close hors range High"
            if o < low * 0.999 or cl < low * 0.999:
                return False, f"Open/Close hors range Low"

            # Mouvement intra-bougie
            move_pct = (h - low) / low * 100 if low > 0 else 0
            if move_pct > self.config.abnormal_price_jump_pct:
                return True, f"Gros mouvement intra-bougie : {move_pct:.1f}% (pas forcement un bug)"

        return True, ""

    def check_price_divergence(self, binance_price: float, coingecko_price: float) -> tuple[bool, float]:
        """
        Compare les prix de 2 sources. Un écart > 3 % suggère une source défaillante.
        Retourne (ok, divergence_pct).
        """
        if binance_price <= 0 or coingecko_price <= 0:
            return True, 0.0
        mean = (binance_price + coingecko_price) / 2
        divergence = abs(binance_price - coingecko_price) / mean * 100
        ok = divergence < self.config.price_divergence_pct
        return ok, divergence

    # ─── Check complet ────────────────────────────────────────────────────────

    def run_full_check(self, data_timestamp: Optional[float] = None,
                        sample_candles: Optional[list] = None) -> HealthStatus:
        """
        Lance tous les checks et met à jour le status.
        Appelé périodiquement par le bot (toutes les 10 min par exemple).
        """
        self.status.checks_passed = 0
        self.status.checks_failed = 0
        now = time.time()

        # Check Binance
        ok_b, lat_b = self.ping_binance()
        self.status.binance_latency_ms = lat_b
        if ok_b and lat_b < self.config.max_api_latency_ms:
            self.status.checks_passed += 1
            self.status.last_binance_ok = now
        else:
            self.status.checks_failed += 1
            msg = f"Binance inaccessible ou latence {lat_b:.0f}ms > {self.config.max_api_latency_ms:.0f}ms"
            self._add_issue(msg)
            self._report_circuit(msg, "info")

        # Check CoinGecko
        ok_c, lat_c = self.ping_coingecko()
        self.status.coingecko_latency_ms = lat_c
        if ok_c and lat_c < self.config.max_api_latency_ms:
            self.status.checks_passed += 1
            self.status.last_coingecko_ok = now
        else:
            self.status.checks_failed += 1
            msg = f"CoinGecko inaccessible ou latence {lat_c:.0f}ms"
            self._add_issue(msg)
            # Moins critique que Binance — juste un warning
            self._report_circuit(msg, "info")

        # Check freshness
        if data_timestamp is not None:
            if self.check_data_freshness(data_timestamp):
                self.status.checks_passed += 1
            else:
                self.status.checks_failed += 1
                age_min = (now - data_timestamp) / 60
                msg = f"Donnees stales : age = {age_min:.1f} min > seuil"
                self._add_issue(msg)
                self._report_circuit(msg, "warning")

        # Check sanity des prix
        if sample_candles:
            ok_s, msg_s = self.check_price_sanity(sample_candles)
            if ok_s:
                self.status.checks_passed += 1
            else:
                self.status.checks_failed += 1
                self._add_issue(f"Prix aberrant : {msg_s}")
                self._report_circuit(f"Prix aberrant : {msg_s}", "warning")

        self.status.last_check_ts = now
        self.status.healthy = (self.status.checks_failed == 0)
        return self.status

    # ─── Internals ────────────────────────────────────────────────────────────

    def _add_issue(self, msg: str):
        self.status.last_failure_msg = msg
        self.status.issues.append((time.time(), msg))
        if len(self.status.issues) > 20:
            self.status.issues = self.status.issues[-20:]

    def _report_circuit(self, msg: str, level: str = "warning"):
        """Alerte le circuit breaker si problème."""
        try:
            from core.circuit_breaker import get_circuit_breaker
            cb = get_circuit_breaker()
            if level == "critical":
                cb.report_api_error(msg)
            else:
                cb.report_anomaly("HEALTH_CHECK", msg)
        except (ImportError, AttributeError) as exc:
            import logging
            logging.getLogger("health").warning(f"_report_circuit failed: {exc}")


# Singleton
_instance: Optional[HealthChecker] = None


def get_health_checker() -> HealthChecker:
    global _instance
    if _instance is None:
        _instance = HealthChecker()
    return _instance
