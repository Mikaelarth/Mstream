"""
MstreamTrader - Module de données de marché
Utilise l'API CoinGecko (gratuite, sans clé API)
"""

import json
import urllib.request
import urllib.error
from datetime import datetime


COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Cryptomonnaies suivies par défaut
DEFAULT_COINS = [
    {"id": "bitcoin",      "symbol": "BTC", "name": "Bitcoin"},
    {"id": "ethereum",     "symbol": "ETH", "name": "Ethereum"},
    {"id": "binancecoin",  "symbol": "BNB", "name": "BNB"},
    {"id": "solana",       "symbol": "SOL", "name": "Solana"},
    {"id": "ripple",       "symbol": "XRP", "name": "XRP"},
    {"id": "cardano",      "symbol": "ADA", "name": "Cardano"},
    {"id": "dogecoin",     "symbol": "DOGE","name": "Dogecoin"},
    {"id": "polkadot",     "symbol": "DOT", "name": "Polkadot"},
]

CURRENCY = "usd"


def _fetch_json(url: str, timeout: int = 10) -> dict | list | None:
    """Effectue une requête HTTP GET et retourne le JSON parsé."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "MstreamTrader/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, Exception):
        return None


def get_prices(coin_ids: list[str] | None = None) -> dict:
    """
    Récupère les prix actuels d'une liste de cryptomonnaies.
    Retourne un dict: { coin_id: {price, change_24h, market_cap, volume} }
    """
    ids = coin_ids or [c["id"] for c in DEFAULT_COINS]
    ids_str = ",".join(ids)
    url = (
        f"{COINGECKO_BASE}/coins/markets"
        f"?vs_currency={CURRENCY}"
        f"&ids={ids_str}"
        f"&order=market_cap_desc"
        f"&per_page=50&page=1"
        f"&sparkline=false"
        f"&price_change_percentage=1h,24h,7d"
    )
    data = _fetch_json(url)
    if not data:
        return {}

    result = {}
    for coin in data:
        result[coin["id"]] = {
            "symbol":       coin.get("symbol", "").upper(),
            "name":         coin.get("name", ""),
            "price":        coin.get("current_price", 0),
            "change_1h":    coin.get("price_change_percentage_1h_in_currency", 0) or 0,
            "change_24h":   coin.get("price_change_percentage_24h", 0) or 0,
            "change_7d":    coin.get("price_change_percentage_7d_in_currency", 0) or 0,
            "market_cap":   coin.get("market_cap", 0),
            "volume_24h":   coin.get("total_volume", 0),
            "high_24h":     coin.get("high_24h", 0),
            "low_24h":      coin.get("low_24h", 0),
            "image":        coin.get("image", ""),
            "last_updated": datetime.now().strftime("%H:%M:%S"),
        }
    return result


# Mapping CoinGecko ID → Binance symbol pour l'API publique klines
_COIN_ID_TO_BINANCE = {
    "bitcoin":     "BTCUSDT",
    "ethereum":    "ETHUSDT",
    "binancecoin": "BNBUSDT",
    "solana":      "SOLUSDT",
    "ripple":      "XRPUSDT",
    "cardano":     "ADAUSDT",
    "dogecoin":    "DOGEUSDT",
    "polkadot":    "DOTUSDT",
}

_BINANCE_PUBLIC = "https://api.binance.com/api/v3"


def get_binance_klines_public(coin_id: str, interval: str = "1h",
                               limit: int = 500) -> list[dict]:
    """
    Récupère les bougies OHLCV depuis Binance public (sans auth).
    Granularités valides: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d
    Limite max: 1000 bougies par appel.

    Retourne [] si le coin n'a pas de correspondance Binance ou si l'API échoue.
    """
    symbol = _COIN_ID_TO_BINANCE.get(coin_id)
    if not symbol:
        return []

    url = (f"{_BINANCE_PUBLIC}/klines"
           f"?symbol={symbol}&interval={interval}&limit={min(limit, 1000)}")
    data = _fetch_json(url)
    if not data or not isinstance(data, list):
        return []

    candles = []
    for k in data:
        if len(k) >= 6:
            candles.append({
                "timestamp": k[0] / 1000,
                "open":      float(k[1]),
                "high":      float(k[2]),
                "low":       float(k[3]),
                "close":     float(k[4]),
                "volume":    float(k[5]),
            })
    return candles


def get_ohlcv_for_analysis(coin_id: str, days: int = 30,
                            interval: str = "1h") -> list[dict]:
    """
    Source OHLCV privilégiée pour l'analyse technique et le backtesting.

    Essaie Binance public en priorité (granularité fine jusqu'à 1h,
    1000 bougies max), puis fallback CoinGecko si échec.

    interval: granularité Binance souhaitée ("1h", "4h", "1d")
    days:     utilisé pour calculer la limite et pour CoinGecko fallback
    """
    # Calcul de la limite selon la granularité
    secs_per_candle = {
        "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
        "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600,
        "12h": 43200, "1d": 86400,
    }.get(interval, 3600)

    limit = min(1000, int(days * 86400 / secs_per_candle) + 50)

    # 1. Essai Binance public
    candles = get_binance_klines_public(coin_id, interval=interval, limit=limit)
    if candles and len(candles) >= 100:
        return candles

    # 2. Fallback CoinGecko
    return get_historical_prices(coin_id, days=days)


def get_historical_prices(coin_id: str, days: int = 30) -> list[dict]:
    """
    Récupère l'historique OHLCV (Open/High/Low/Close/Volume).
    Retourne une liste de dict: [{timestamp, open, high, low, close, volume}]
    """
    url = (
        f"{COINGECKO_BASE}/coins/{coin_id}/ohlc"
        f"?vs_currency={CURRENCY}&days={days}"
    )
    data = _fetch_json(url)
    if not data:
        return []

    # Format CoinGecko OHLC: [timestamp_ms, open, high, low, close]
    candles = []
    for item in data:
        if len(item) >= 5:
            candles.append({
                "timestamp": item[0] / 1000,
                "open":      item[1],
                "high":      item[2],
                "low":       item[3],
                "close":     item[4],
            })
    return candles


def get_coin_detail(coin_id: str) -> dict:
    """
    Récupère les détails complets d'une cryptomonnaie.
    """
    url = (
        f"{COINGECKO_BASE}/coins/{coin_id}"
        f"?localization=false&tickers=false&community_data=false&developer_data=false"
    )
    data = _fetch_json(url)
    if not data:
        return {}

    market = data.get("market_data", {})
    return {
        "id":           data.get("id", ""),
        "symbol":       data.get("symbol", "").upper(),
        "name":         data.get("name", ""),
        "description":  data.get("description", {}).get("en", ""),
        "price":        market.get("current_price", {}).get(CURRENCY, 0),
        "ath":          market.get("ath", {}).get(CURRENCY, 0),
        "atl":          market.get("atl", {}).get(CURRENCY, 0),
        "market_cap":   market.get("market_cap", {}).get(CURRENCY, 0),
        "circulating_supply": market.get("circulating_supply", 0),
        "total_supply":       market.get("total_supply", 0),
    }


def format_price(value: float) -> str:
    """Formate un prix pour l'affichage."""
    if value >= 1000:
        return f"${value:,.2f}"
    elif value >= 1:
        return f"${value:.4f}"
    else:
        return f"${value:.6f}"


def format_large_number(value: float) -> str:
    """Formate les grands nombres (market cap, volume)."""
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    elif value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    elif value >= 1_000:
        return f"${value / 1_000:.2f}K"
    return f"${value:.2f}"
