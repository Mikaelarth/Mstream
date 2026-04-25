"""
MstreamTrader - Connecteur Binance
Connexion à l'API Binance officielle pour :
- Récupérer le solde réel du compte
- Passer des ordres réels (market, limit)
- Suivre les ordres ouverts
Utilise uniquement urllib (pas de dépendance externe)
"""

import hashlib
import hmac
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime

from core.net import SSL_CTX, explain_url_error


BINANCE_BASE = "https://api.binance.com"


class BinanceError(Exception):
    pass


# Import paresseux pour éviter cycle (retry → exchange → retry)
def _retry_decorator():
    from core.retry import retry_binance
    return retry_binance(max_attempts=3, initial_delay=0.5, backoff_factor=2.0)


class BinanceClient:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key      = api_key.strip()
        self.api_secret   = api_secret.strip()
        self._symbol_info = {}   # cache des filters par symbole (LOT_SIZE, PRICE_FILTER)

    def _sign(self, params: dict) -> str:
        query = urllib.parse.urlencode(params)
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict | None = None,
        signed: bool = False,
    ) -> dict | list:
        """
        Appel HTTP Binance avec retry automatique sur erreurs transitoires
        (timeout, 5xx, rate limit -1003, disconnected -1001).
        Les erreurs permanentes (400, 401, invalid keys) remontent immédiatement.
        """
        from core.retry import retry_binance

        @retry_binance(max_attempts=3, initial_delay=0.5, backoff_factor=2.0)
        def _do_request():
            p = dict(params or {})
            if signed:
                # NOTE : timestamp recalculé à CHAQUE tentative (important pour -1021)
                p["timestamp"]  = int(time.time() * 1000)
                p["recvWindow"] = 5000
                p["signature"]  = self._sign(p)

            url = f"{BINANCE_BASE}{endpoint}"
            query_string = urllib.parse.urlencode(p)

            if method == "GET":
                if query_string:
                    full_url = f"{url}?{query_string}"
                else:
                    full_url = url
                req = urllib.request.Request(full_url)
            else:
                data = query_string.encode("utf-8")
                req  = urllib.request.Request(url, data=data)
                req.add_header("Content-Type", "application/x-www-form-urlencoded")

            req.add_header("X-MBX-APIKEY", self.api_key)

            try:
                # context=SSL_CTX critique sur Android — sinon HTTPS échoue
                # silencieusement (pas de chaîne de CAs valide).
                with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
                    body = resp.read().decode("utf-8")
                    return json.loads(body)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8")
                try:
                    err = json.loads(body)
                    raise BinanceError(f"Binance {e.code}: {err.get('msg', body)}")
                except json.JSONDecodeError:
                    raise BinanceError(f"Binance HTTP {e.code}: {body}")
            except urllib.error.URLError as e:
                raise BinanceError(f"Connexion impossible : {explain_url_error(e)}")

        return _do_request()

    # ── Compte ────────────────────────────────────────────────────────────────

    def test_connection(self) -> bool:
        """Teste la connectivité à l'API Binance."""
        try:
            self._request("GET", "/api/v3/ping")
            return True
        except BinanceError:
            return False

    def get_account(self) -> dict:
        """Récupère les informations du compte (balances)."""
        data = self._request("GET", "/api/v3/account", signed=True)
        balances = {}
        for b in data.get("balances", []):
            free   = float(b["free"])
            locked = float(b["locked"])
            if free > 0 or locked > 0:
                balances[b["asset"]] = {
                    "free":   free,
                    "locked": locked,
                    "total":  free + locked,
                }
        return {
            "balances":       balances,
            "can_trade":      data.get("canTrade", False),
            "can_withdraw":   data.get("canWithdraw", False),
            "account_type":   data.get("accountType", ""),
        }

    def get_usdt_balance(self) -> float:
        """Retourne uniquement le solde USDT disponible."""
        account = self.get_account()
        return account["balances"].get("USDT", {}).get("free", 0.0)

    # ── Prix ─────────────────────────────────────────────────────────────────

    def get_price(self, symbol: str) -> float:
        """Prix actuel d'un symbole (ex: BTCUSDT)."""
        data = self._request("GET", "/api/v3/ticker/price",
                             {"symbol": symbol.upper()})
        return float(data.get("price", 0))

    def get_24h_stats(self, symbol: str) -> dict:
        """Statistiques 24h d'un symbole."""
        data = self._request("GET", "/api/v3/ticker/24hr",
                             {"symbol": symbol.upper()})
        return {
            "price":       float(data.get("lastPrice", 0)),
            "change_pct":  float(data.get("priceChangePercent", 0)),
            "high":        float(data.get("highPrice", 0)),
            "low":         float(data.get("lowPrice", 0)),
            "volume":      float(data.get("volume", 0)),
            "quote_vol":   float(data.get("quoteVolume", 0)),
        }

    def get_klines(self, symbol: str, interval: str = "1h", limit: int = 100) -> list[dict]:
        """
        Chandelles OHLCV depuis Binance.
        Intervalles: 1m, 5m, 15m, 1h, 4h, 1d
        """
        data = self._request("GET", "/api/v3/klines", {
            "symbol":   symbol.upper(),
            "interval": interval,
            "limit":    limit,
        })
        candles = []
        for k in data:
            candles.append({
                "timestamp": k[0] / 1000,
                "open":      float(k[1]),
                "high":      float(k[2]),
                "low":       float(k[3]),
                "close":     float(k[4]),
                "volume":    float(k[5]),
            })
        return candles

    # ── Ordres ────────────────────────────────────────────────────────────────

    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict:
        """
        Passe un ordre MARKET (exécution immédiate au prix du marché).
        side: 'BUY' ou 'SELL'
        quantity: quantité de la cryptomonnaie (ex: 0.001 pour 0.001 BTC)
        """
        params = {
            "symbol":   symbol.upper(),
            "side":     side.upper(),
            "type":     "MARKET",
            "quantity": self._format_quantity(quantity, symbol),
        }
        data = self._request("POST", "/api/v3/order", params, signed=True)
        return self._parse_order(data)

    def place_market_order_usdt(
        self,
        symbol: str,
        side: str,
        quote_qty: float,
    ) -> dict:
        """
        Ordre MARKET en spécifiant un montant en USDT (quoteOrderQty).
        Idéal pour les achats auto : on définit combien de USDT dépenser.
        side: 'BUY' ou 'SELL'
        quote_qty: montant en USDT à dépenser / recevoir
        """
        params = {
            "symbol":        symbol.upper(),
            "side":          side.upper(),
            "type":          "MARKET",
            "quoteOrderQty": f"{quote_qty:.2f}",
        }
        data = self._request("POST", "/api/v3/order", params, signed=True)
        return self._parse_order(data)

    def place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
    ) -> dict:
        """
        Passe un ordre LIMIT (s'exécute quand le prix atteint le niveau voulu).
        """
        params = {
            "symbol":      symbol.upper(),
            "side":        side.upper(),
            "type":        "LIMIT",
            "timeInForce": "GTC",
            "quantity":    self._format_quantity(quantity, symbol),
            "price":       self._format_price(price, symbol),
        }
        data = self._request("POST", "/api/v3/order", params, signed=True)
        return self._parse_order(data)

    def place_stop_loss_market(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_price: float,
    ) -> dict:
        """
        Ordre STOP_LOSS (MARKET au déclenchement) — recommandé pour les SL.
        Garantit l'exécution même en gap down, contrairement à STOP_LOSS_LIMIT
        qui peut ne jamais s'exécuter si le prix saute sous le limit.
        """
        params = {
            "symbol":    symbol.upper(),
            "side":      side.upper(),
            "type":      "STOP_LOSS",
            "quantity":  self._format_quantity(quantity, symbol),
            "stopPrice": self._format_price(stop_price, symbol),
        }
        data = self._request("POST", "/api/v3/order", params, signed=True)
        return self._parse_order(data)

    def place_stop_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_price: float,
        limit_price: float,
    ) -> dict:
        """
        Ordre STOP-LIMIT (DÉCONSEILLÉ) — conservé pour compatibilité.
        ⚠ Risque de non-exécution en cas de gap : préférer place_stop_loss_market().
        """
        params = {
            "symbol":      symbol.upper(),
            "side":        side.upper(),
            "type":        "STOP_LOSS_LIMIT",
            "timeInForce": "GTC",
            "quantity":    self._format_quantity(quantity, symbol),
            "stopPrice":   self._format_price(stop_price, symbol),
            "price":       self._format_price(limit_price, symbol),
        }
        data = self._request("POST", "/api/v3/order", params, signed=True)
        return self._parse_order(data)

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        """Annule un ordre ouvert."""
        data = self._request("DELETE", "/api/v3/order", {
            "symbol":  symbol.upper(),
            "orderId": order_id,
        }, signed=True)
        return self._parse_order(data)

    def get_open_orders(self, symbol: str | None = None) -> list[dict]:
        """Liste les ordres ouverts."""
        params = {}
        if symbol:
            params["symbol"] = symbol.upper()
        data = self._request("GET", "/api/v3/openOrders", params, signed=True)
        return [self._parse_order(o) for o in data]

    def get_order_history(self, symbol: str, limit: int = 50) -> list[dict]:
        """Historique des ordres d'un symbole."""
        data = self._request("GET", "/api/v3/allOrders", {
            "symbol": symbol.upper(),
            "limit":  limit,
        }, signed=True)
        return [self._parse_order(o) for o in data]

    # ── Helpers ───────────────────────────────────────────────────────────────

    # Précisions de FALLBACK si /exchangeInfo indisponible (conservatrices)
    _FALLBACK_PRECISIONS = {
        "BTCUSDT": 5, "ETHUSDT": 4, "BNBUSDT": 3,
        "SOLUSDT": 2, "XRPUSDT": 0, "ADAUSDT": 0,
        "DOGEUSDT": 0, "DOTUSDT": 2,
    }

    def _load_symbol_info(self, symbol: str) -> dict:
        """
        Récupère et cache les filters Binance d'un symbole (LOT_SIZE, PRICE_FILTER).
        Évite les rejets d'ordres pour précision invalide.
        """
        sym = symbol.upper()
        if sym in self._symbol_info:
            return self._symbol_info[sym]

        try:
            data = self._request("GET", "/api/v3/exchangeInfo", {"symbol": sym})
            symbols = data.get("symbols", [])
            if not symbols:
                raise BinanceError("symbol inconnu")

            info = symbols[0]
            filters = {f["filterType"]: f for f in info.get("filters", [])}

            lot      = filters.get("LOT_SIZE", {})
            price_f  = filters.get("PRICE_FILTER", {})
            min_not  = filters.get("MIN_NOTIONAL", filters.get("NOTIONAL", {}))

            step_size = float(lot.get("stepSize", "0.00001"))
            tick_size = float(price_f.get("tickSize", "0.01"))

            self._symbol_info[sym] = {
                "base_asset":   info.get("baseAsset", ""),
                "quote_asset":  info.get("quoteAsset", ""),
                "step_size":    step_size,
                "tick_size":    tick_size,
                "qty_decimals": self._decimals_from_step(step_size),
                "price_decimals": self._decimals_from_step(tick_size),
                "min_notional": float(min_not.get("minNotional", "5.0")),
            }
        except BinanceError:
            # Fallback silencieux si l'appel échoue (réseau / rate limit)
            decimals = self._FALLBACK_PRECISIONS.get(sym, 2)
            self._symbol_info[sym] = {
                "base_asset":     sym.replace("USDT", ""),
                "quote_asset":    "USDT",
                "step_size":      10 ** -decimals,
                "tick_size":      0.01,
                "qty_decimals":   decimals,
                "price_decimals": 2 if sym.endswith("USDT") and "BTC" not in sym else 4,
                "min_notional":   5.0,
            }
        return self._symbol_info[sym]

    @staticmethod
    def _decimals_from_step(step: float) -> int:
        """Nombre de décimales nécessaires pour formater selon le step."""
        if step >= 1:
            return 0
        s = f"{step:.10f}".rstrip("0")
        if "." not in s:
            return 0
        return len(s.split(".")[1])

    @staticmethod
    def _round_to_step(value: float, step: float) -> float:
        """Tronque une valeur au multiple inférieur du step (évite OVER_SIZE)."""
        if step <= 0:
            return value
        # Division entière puis remultiplication — éviter l'accumulation d'erreurs flottantes
        import math
        return math.floor(value / step) * step

    def _format_quantity(self, qty: float, symbol: str) -> str:
        """Formatage quantité selon stepSize réel du symbole."""
        info     = self._load_symbol_info(symbol)
        rounded  = self._round_to_step(qty, info["step_size"])
        return f"{rounded:.{info['qty_decimals']}f}"

    def _format_price(self, price: float, symbol: str) -> str:
        """Formatage prix selon tickSize réel du symbole."""
        info    = self._load_symbol_info(symbol)
        rounded = self._round_to_step(price, info["tick_size"])
        return f"{rounded:.{info['price_decimals']}f}"

    def _parse_order(self, data: dict) -> dict:
        """Normalise un objet ordre Binance. Robuste aux champs manquants / qty=0."""
        executed_qty = float(data.get("executedQty", 0) or 0)
        quote_qty    = float(data.get("cummulativeQuoteQty", 0) or 0)
        avg_price    = (quote_qty / executed_qty) if executed_qty > 0 else 0.0

        # Normaliser fills éventuels (pour ordres market avec multiple fills)
        fills = data.get("fills", []) or []
        if not avg_price and fills:
            try:
                total_qty  = sum(float(f.get("qty", 0)) for f in fills)
                total_cost = sum(float(f.get("price", 0)) * float(f.get("qty", 0)) for f in fills)
                avg_price  = total_cost / total_qty if total_qty > 0 else 0.0
            except (TypeError, ValueError):
                pass

        return {
            "order_id":    data.get("orderId", ""),
            "symbol":      data.get("symbol", ""),
            "side":        data.get("side", ""),
            "type":        data.get("type", ""),
            "status":      data.get("status", ""),
            "quantity":    float(data.get("origQty", 0) or 0),
            "filled":      executed_qty,
            "executed_qty": executed_qty,
            "price":       float(data.get("price", 0) or 0),
            "avg_price":   avg_price,
            "fills":       fills,
            "time":        (datetime.fromtimestamp(data.get("time", 0) / 1000).strftime("%Y-%m-%d %H:%M")
                            if data.get("time") else ""),
        }


# Cache singleton du client Binance (évite de recréer le client + recharger
# exchangeInfo à chaque appel — optimisation rate limit + latence)
_client_cache: BinanceClient | None = None
_client_cache_keys: tuple | None = None


def get_client() -> BinanceClient | None:
    """
    Crée (ou récupère depuis le cache) le client Binance.
    Le cache est invalidé si les clés API changent en DB.
    """
    global _client_cache, _client_cache_keys
    from core.database import get_setting_encrypted
    api_key    = get_setting_encrypted("binance_api_key")
    api_secret = get_setting_encrypted("binance_api_secret")
    if not api_key or not api_secret:
        _client_cache = None
        _client_cache_keys = None
        return None
    current_keys = (api_key, api_secret)
    if _client_cache is None or _client_cache_keys != current_keys:
        _client_cache = BinanceClient(api_key, api_secret)
        _client_cache_keys = current_keys
    return _client_cache


def invalidate_client_cache():
    """Force la recréation du client (utile après changement de clés)."""
    global _client_cache, _client_cache_keys
    _client_cache = None
    _client_cache_keys = None


def execute_signal_trade(signal_obj, quantity_usdt: float) -> dict:
    """
    Exécute un trade basé sur un signal avec gestion du risque.
    quantity_usdt: montant en USDT à investir.
    """
    from core.database import record_trade, get_setting

    client = get_client()
    if not client:
        raise BinanceError("Clés API Binance non configurées")

    symbol = f"{signal_obj.symbol}USDT"
    price  = signal_obj.price

    if price <= 0:
        raise BinanceError("Prix invalide")

    from core.signals import Signal
    side = "BUY" if signal_obj.signal in (Signal.BUY, Signal.STRONG_BUY) else "SELL"
    quantity = quantity_usdt / price

    # Passer l'ordre market
    order = client.place_market_order(symbol, side, quantity)

    # Enregistrer en base
    actual_price = order.get("avg_price", price)
    actual_qty   = order.get("filled", quantity)
    fee          = actual_qty * actual_price * 0.001  # 0.1% frais Binance

    record_trade(
        coin_id     = signal_obj.coin_id,
        symbol      = signal_obj.symbol,
        side        = side,
        quantity    = actual_qty,
        price       = actual_price,
        fee         = fee,
        source      = "AUTO_SIGNAL",
        note        = f"Signal {signal_obj.signal.value} score={signal_obj.score}",
        exchange_id = str(order.get("order_id", "")),
    )

    # Placer un stop-loss MARKET (garantit l'exécution en gap down)
    if side == "BUY" and signal_obj.stop_loss > 0:
        try:
            client.place_stop_loss_market(
                symbol,
                "SELL",
                actual_qty,
                stop_price=signal_obj.stop_loss,
            )
        except BinanceError:
            pass  # Stop-loss optionnel, ne bloque pas le trade principal

    return order
