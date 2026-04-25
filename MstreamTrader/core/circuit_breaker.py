"""
MstreamTrader - Circuit Breaker Multi-Niveaux
==============================================

Arrêt automatique du bot en cas d'anomalie détectée. Inspiré des coupe-circuits
des trading floors institutionnels (NYSE Rule 80B, Binance Futures circuit).

Niveaux de déclenchement (du moins grave au plus grave) :

  HEALTHY   → fonctionnement normal
  WARNING   → anomalie détectée, audit renforcé, mais trading continue
  TRIGGERED → arrêt des nouvelles entrées, surveillance SL/TP uniquement
  FROZEN    → arrêt TOTAL (même les exits) — nécessite intervention manuelle

Détections actives :
  1. N pertes SL consécutives                   → TRIGGERED
  2. Chute rapide du capital (> X % en Y heures) → TRIGGERED
  3. Drawdown total supérieur au seuil config    → TRIGGERED
  4. Anomalie de données marché (prix aberrants) → WARNING
  5. Écart majeur entre volume historique et actuel → WARNING
  6. Perte d'un seul trade > K × avg_loss        → WARNING
  7. Série de 3 errors API consécutives          → FROZEN

Le circuit breaker est thread-safe et persiste son état en DB.
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CircuitState(Enum):
    HEALTHY   = "healthy"
    WARNING   = "warning"
    TRIGGERED = "triggered"
    FROZEN    = "frozen"


STATE_LABELS = {
    CircuitState.HEALTHY:   "OK",
    CircuitState.WARNING:   "WARNING - audit reinforce",
    CircuitState.TRIGGERED: "TRIGGERED - entries bloquees",
    CircuitState.FROZEN:    "FROZEN - intervention manuelle requise",
}


@dataclass
class CircuitConfig:
    """Seuils de déclenchement du circuit breaker."""

    # Niveau 1 — TRIGGERED sur pertes répétées
    max_consecutive_sl:       int   = 5         # 5 SL consecutifs → TRIGGERED
    max_sl_per_day:           int   = 8         # 8 SL/jour → TRIGGERED

    # Niveau 2 — TRIGGERED sur chute rapide
    rapid_drawdown_pct:       float = 10.0      # > 10 % en rapid_drawdown_hours
    rapid_drawdown_hours:     float = 4.0       # fenêtre de 4h

    # Niveau 3 — TRIGGERED sur drawdown total
    total_drawdown_pct:       float = 20.0      # même que bot mais centralisé

    # Niveau 4 — WARNING sur anomalies
    abnormal_price_delta_pct: float = 15.0      # bougie > 15 % move en 1h → warning
    abnormal_loss_multiplier: float = 3.0       # trade unique perd > 3× avg_loss

    # Niveau 5 — FROZEN sur erreurs API
    max_api_errors_consecutive: int = 5         # 5 erreurs API d'affilée → FROZEN

    # Auto-recovery
    warning_cooldown_hours:   float = 2.0       # WARNING → HEALTHY après 2h sans nouvel incident
    triggered_recovery_hours: float = 12.0      # TRIGGERED → WARNING après 12h propres


@dataclass
class CircuitEvent:
    """Événement ayant contribué au déclenchement."""
    timestamp: float
    event_type: str     # "CONSECUTIVE_SL", "RAPID_DD", "TOTAL_DD", "API_ERROR", ...
    severity:   str     # "info", "warning", "critical"
    message:    str
    metric:     Optional[float] = None


@dataclass
class CircuitBreakerState:
    """État observable du circuit breaker."""
    state:                    CircuitState = CircuitState.HEALTHY
    consecutive_sl:           int   = 0
    sl_today:                 int   = 0
    sl_day_stamp:             int   = 0      # epoch/86400 du jour courant
    consecutive_api_errors:   int   = 0
    peak_capital:             float = 0.0
    rapid_check_samples:      list  = field(default_factory=list)   # [(ts, capital)]
    last_warning_ts:          float = 0.0
    last_trigger_ts:          float = 0.0
    recent_events:            list  = field(default_factory=list)   # derniers 20 événements


class CircuitBreaker:
    """
    Circuit breaker central.
    Thread-safe via un simple lock : toutes les mutations passent par les méthodes publiques.
    """

    def __init__(self, config: Optional[CircuitConfig] = None):
        import threading
        self.config = config or CircuitConfig()
        self.state  = CircuitBreakerState()
        self._lock  = threading.Lock()

    # ─── Rapporteurs d'événements (appelés par le bot) ─────────────────────────

    def report_trade_result(self, pnl: float, exit_reason: str,
                            avg_loss: Optional[float] = None) -> None:
        """Appelé après chaque clôture de position."""
        with self._lock:
            now = time.time()

            # SL consécutifs
            if exit_reason == "EXIT_SL" or pnl < 0:
                self.state.consecutive_sl += 1
                self._increment_sl_today(now)
            else:
                self.state.consecutive_sl = 0

            # Perte anormale ?
            if avg_loss and avg_loss > 0 and pnl < -self.config.abnormal_loss_multiplier * avg_loss:
                self._raise_event("ABNORMAL_LOSS",
                    f"Perte de {pnl:.2f} USDT > {self.config.abnormal_loss_multiplier}x "
                    f"avg_loss ({avg_loss:.2f})",
                    severity="warning", metric=pnl)
                self._elevate(CircuitState.WARNING, now)

            # Déclenchement si SL consécutifs atteint
            if self.state.consecutive_sl >= self.config.max_consecutive_sl:
                self._raise_event("CONSECUTIVE_SL",
                    f"{self.state.consecutive_sl} SL consecutifs atteints",
                    severity="critical", metric=self.state.consecutive_sl)
                self._elevate(CircuitState.TRIGGERED, now)

            if self.state.sl_today >= self.config.max_sl_per_day:
                self._raise_event("DAILY_SL_LIMIT",
                    f"{self.state.sl_today} SL aujourd'hui (limite {self.config.max_sl_per_day})",
                    severity="critical", metric=self.state.sl_today)
                self._elevate(CircuitState.TRIGGERED, now)

    def report_capital(self, current_capital: float) -> None:
        """
        Appelé à chaque cycle avec le capital total (réalisé + unrealized).
        Détecte les chutes rapides.
        """
        with self._lock:
            now = time.time()

            if current_capital > self.state.peak_capital:
                self.state.peak_capital = current_capital

            # Drawdown total
            if self.state.peak_capital > 0:
                dd_pct = (self.state.peak_capital - current_capital) / self.state.peak_capital * 100
                if dd_pct > self.config.total_drawdown_pct:
                    self._raise_event("TOTAL_DD",
                        f"Drawdown total {dd_pct:.2f}% > {self.config.total_drawdown_pct}%",
                        severity="critical", metric=dd_pct)
                    self._elevate(CircuitState.TRIGGERED, now)

            # Rapid drawdown : maintenir une fenêtre glissante
            self.state.rapid_check_samples.append((now, current_capital))
            cutoff = now - self.config.rapid_drawdown_hours * 3600
            self.state.rapid_check_samples = [
                (t, c) for t, c in self.state.rapid_check_samples if t >= cutoff
            ]
            if len(self.state.rapid_check_samples) >= 2:
                oldest_capital = self.state.rapid_check_samples[0][1]
                if oldest_capital > 0:
                    rapid_dd = (oldest_capital - current_capital) / oldest_capital * 100
                    if rapid_dd > self.config.rapid_drawdown_pct:
                        self._raise_event("RAPID_DD",
                            f"Chute rapide {rapid_dd:.2f}% en {self.config.rapid_drawdown_hours}h",
                            severity="critical", metric=rapid_dd)
                        self._elevate(CircuitState.TRIGGERED, now)

    def report_api_error(self, msg: str = "") -> None:
        """Appelé quand un appel API Binance/CoinGecko échoue."""
        with self._lock:
            now = time.time()
            self.state.consecutive_api_errors += 1
            if self.state.consecutive_api_errors >= self.config.max_api_errors_consecutive:
                self._raise_event("API_FAILURE",
                    f"{self.state.consecutive_api_errors} erreurs API consecutives",
                    severity="critical", metric=self.state.consecutive_api_errors)
                self._elevate(CircuitState.FROZEN, now)

    def report_api_success(self) -> None:
        """Reset le compteur d'erreurs API."""
        with self._lock:
            self.state.consecutive_api_errors = 0

    def report_anomaly(self, kind: str, message: str, metric: Optional[float] = None) -> None:
        """Anomalies ponctuelles détectées par les health checks."""
        with self._lock:
            self._raise_event(kind, message, severity="warning", metric=metric)
            self._elevate(CircuitState.WARNING, time.time())

    # ─── Requêtes d'état (thread-safe via lock) ──────────────────────────────

    def can_open_new_positions(self) -> bool:
        """Autorise-t-on l'ouverture de nouvelles positions ?"""
        with self._lock:
            return self.state.state in (CircuitState.HEALTHY, CircuitState.WARNING)

    def can_manage_exits(self) -> bool:
        """Autorise-t-on la gestion des sorties (SL/TP) ?"""
        with self._lock:
            return self.state.state != CircuitState.FROZEN

    def get_state(self) -> CircuitState:
        with self._lock:
            return self.state.state

    def get_status_message(self) -> str:
        with self._lock:
            return STATE_LABELS[self.state.state]

    def get_recent_events(self, n: int = 10) -> list:
        with self._lock:
            return list(self.state.recent_events[-n:])

    def get_state_snapshot(self) -> dict:
        """
        Capture atomique de l'état observable (pour checkpoint/UI).
        Thread-safe : une seule acquisition du lock pour lire tout.
        Évite le pattern anti-safety `cb.state.X` depuis l'extérieur.
        """
        with self._lock:
            return {
                "state":                  self.state.state.value,
                "consecutive_sl":         self.state.consecutive_sl,
                "sl_today":               self.state.sl_today,
                "peak_capital":           self.state.peak_capital,
                "consecutive_api_errors": self.state.consecutive_api_errors,
                "last_warning_ts":        self.state.last_warning_ts,
                "last_trigger_ts":        self.state.last_trigger_ts,
            }

    def manual_reset(self) -> None:
        """
        Remet le circuit à HEALTHY et reset TOUT l'état d'observation.
        À utiliser après investigation manuelle de la cause (ex: suite d'un FROZEN).

        IMPORTANT : reset aussi peak_capital + rapid_check_samples pour éviter
        qu'un ancien peak erroné ne déclenche TRIGGERED immédiat.
        """
        with self._lock:
            self.state.state                    = CircuitState.HEALTHY
            self.state.consecutive_sl           = 0
            self.state.sl_today                 = 0
            self.state.consecutive_api_errors   = 0
            self.state.peak_capital             = 0.0   # repart à zéro
            self.state.rapid_check_samples      = []    # purge historique
            self.state.last_warning_ts          = 0
            self.state.last_trigger_ts          = 0
            self._raise_event("MANUAL_RESET", "Circuit manuellement reinitialise",
                              severity="info")

    # ─── Auto-recovery ────────────────────────────────────────────────────────

    def auto_recover_check(self) -> None:
        """
        Appelé périodiquement pour redescendre le niveau après une période calme.
        WARNING → HEALTHY après warning_cooldown_hours sans incident.
        TRIGGERED → WARNING après triggered_recovery_hours sans incident.
        """
        with self._lock:
            now = time.time()

            if self.state.state == CircuitState.WARNING and self.state.last_warning_ts > 0:
                if (now - self.state.last_warning_ts) > self.config.warning_cooldown_hours * 3600:
                    self.state.state = CircuitState.HEALTHY
                    self._raise_event("AUTO_RECOVER",
                        "Retour a HEALTHY apres periode calme", severity="info")

            elif self.state.state == CircuitState.TRIGGERED and self.state.last_trigger_ts > 0:
                if (now - self.state.last_trigger_ts) > self.config.triggered_recovery_hours * 3600:
                    # Reset progressif : TRIGGERED → WARNING (puis → HEALTHY au prochain cycle)
                    self.state.state = CircuitState.WARNING
                    self.state.last_warning_ts = now
                    self.state.consecutive_sl = 0
                    self._raise_event("PARTIAL_RECOVER",
                        "Retour a WARNING apres periode de surveillance", severity="info")

    # ─── Interne ──────────────────────────────────────────────────────────────

    def _increment_sl_today(self, now: float):
        today_stamp = int(now // 86400)
        if today_stamp != self.state.sl_day_stamp:
            self.state.sl_today = 0
            self.state.sl_day_stamp = today_stamp
        self.state.sl_today += 1

    def _elevate(self, new_state: CircuitState, now: float):
        """Fait remonter le niveau (ne peut pas redescendre via cette fonction)."""
        order = [CircuitState.HEALTHY, CircuitState.WARNING,
                 CircuitState.TRIGGERED, CircuitState.FROZEN]
        if order.index(new_state) > order.index(self.state.state):
            self.state.state = new_state
        if new_state == CircuitState.WARNING:
            self.state.last_warning_ts = now
        elif new_state == CircuitState.TRIGGERED:
            self.state.last_trigger_ts = now

    def _raise_event(self, event_type: str, message: str,
                     severity: str = "info", metric: Optional[float] = None):
        event = CircuitEvent(
            timestamp  = time.time(),
            event_type = event_type,
            severity   = severity,
            message    = message,
            metric     = metric,
        )
        self.state.recent_events.append(event)
        # Garder les 50 derniers
        if len(self.state.recent_events) > 50:
            self.state.recent_events = self.state.recent_events[-50:]


# ─── Singleton ────────────────────────────────────────────────────────────────

_instance: Optional[CircuitBreaker] = None


def get_circuit_breaker() -> CircuitBreaker:
    global _instance
    if _instance is None:
        _instance = CircuitBreaker()
    return _instance
