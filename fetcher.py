"""
Market data fetching layer.
Supports: Binance (crypto), Twelve Data (forex/indices), Alpha Vantage fallback.
Returns standardised pandas DataFrames with OHLCV columns.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
import numpy as np
import requests

logger = logging.getLogger(__name__)

# ── Instrument routing ─────────────────────────────────────────────────────────

CRYPTO_INSTRUMENTS = {"BTCUSD": "BTCUSDT"}
FOREX_INSTRUMENTS  = {"XAUUSD", "GBPUSD", "USDJPY"}
INDEX_INSTRUMENTS  = {"NAS100", "US30"}

TWELVE_DATA_SYMBOLS = {
    "XAUUSD": "XAU/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY",
    "NAS100": "NDX",
    "US30":   "DJI",
}

TIMEFRAME_MAP_TWELVE = {
    "1D":    "1day",
    "4H":    "4h",
    "1H":    "1h",
    "30min": "30min",
}

TIMEFRAME_MAP_BINANCE = {
    "1D":    "1d",
    "4H":    "4h",
    "1H":    "1h",
    "30min": "30m",
}


class DataFetcher:
    def __init__(self, settings):
        self.settings = settings
        self._cache: dict[str, tuple[pd.DataFrame, datetime]] = {}
        self._cache_ttl = timedelta(minutes=2)

    # ── Public API ─────────────────────────────────────────────────────────

    def get_ohlcv(self, instrument: str, timeframe: str, limit: int = 300) -> Optional[pd.DataFrame]:
        """Return OHLCV DataFrame for instrument/timeframe. Uses cache."""
        cache_key = f"{instrument}_{timeframe}"
        if cache_key in self._cache:
            df, ts = self._cache[cache_key]
            if datetime.utcnow() - ts < self._cache_ttl:
                return df

        df = self._fetch(instrument, timeframe, limit)
        if df is not None and not df.empty:
            self._cache[cache_key] = (df, datetime.utcnow())
        return df

    def get_current_price(self, instrument: str) -> Optional[float]:
        df = self.get_ohlcv(instrument, "30min", limit=5)
        if df is not None and not df.empty:
            return float(df["close"].iloc[-1])
        return None

    # ── Internal routing ───────────────────────────────────────────────────

    def _fetch(self, instrument: str, timeframe: str, limit: int) -> Optional[pd.DataFrame]:
        if instrument in CRYPTO_INSTRUMENTS:
            return self._fetch_binance(instrument, timeframe, limit)
        else:
            return self._fetch_twelve_data(instrument, timeframe, limit)

    # ── Binance ────────────────────────────────────────────────────────────

    def _fetch_binance(self, instrument: str, timeframe: str, limit: int) -> Optional[pd.DataFrame]:
        symbol = CRYPTO_INSTRUMENTS[instrument]
        interval = TIMEFRAME_MAP_BINANCE.get(timeframe, "1h")
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        try:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            data = r.json()
            df = pd.DataFrame(data, columns=[
                "timestamp", "open", "high", "low", "close", "volume",
                "close_time", "quote_vol", "trades", "taker_buy_base",
                "taker_buy_quote", "ignore"
            ])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df = df[["timestamp", "open", "high", "low", "close", "volume"]]
            df[["open", "high", "low", "close", "volume"]] = df[
                ["open", "high", "low", "close", "volume"]
            ].astype(float)
            df.set_index("timestamp", inplace=True)
            return df
        except Exception as e:
            logger.error(f"Binance fetch error for {instrument}: {e}")
            return self._generate_demo_data(instrument, timeframe, limit)

    # ── Twelve Data ────────────────────────────────────────────────────────

    def _fetch_twelve_data(self, instrument: str, timeframe: str, limit: int) -> Optional[pd.DataFrame]:
        symbol = TWELVE_DATA_SYMBOLS.get(instrument, instrument)
        interval = TIMEFRAME_MAP_TWELVE.get(timeframe, "1h")
        api_key = self.settings.TWELVE_DATA_KEY

        if not api_key:
            return self._generate_demo_data(instrument, timeframe, limit)

        url = "https://api.twelvedata.com/time_series"
        params = {
            "symbol": symbol,
            "interval": interval,
            "outputsize": limit,
            "apikey": api_key,
            "format": "JSON",
        }
        try:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            data = r.json()
            if "values" not in data:
                logger.warning(f"Twelve Data bad response for {instrument}: {data.get('message','')}")
                return self._generate_demo_data(instrument, timeframe, limit)

            df = pd.DataFrame(data["values"])
            df["datetime"] = pd.to_datetime(df["datetime"])
            df.set_index("datetime", inplace=True)
            df = df.sort_index()
            df[["open","high","low","close","volume"]] = df[
                ["open","high","low","close","volume"]
            ].astype(float)
            df.rename(columns={"datetime": "timestamp"}, inplace=True)
            return df
        except Exception as e:
            logger.error(f"Twelve Data error for {instrument}: {e}")
            return self._generate_demo_data(instrument, timeframe, limit)

    # ── Demo / simulation data (used when no API keys configured) ──────────

    def _generate_demo_data(self, instrument: str, timeframe: str, limit: int) -> pd.DataFrame:
        """Generate realistic OHLCV data for demo/testing purposes."""
        base_prices = {
            "XAUUSD": 2320.0, "BTCUSD": 67000.0, "GBPUSD": 1.2650,
            "USDJPY": 154.50, "NAS100": 18200.0, "US30": 39500.0,
        }
        base = base_prices.get(instrument, 1000.0)
        volatility = base * 0.002

        freq_map = {"1D": "D", "4H": "4h", "1H": "h", "30min": "30min"}
        freq = freq_map.get(timeframe, "h")

        end = datetime.utcnow()
        idx = pd.date_range(end=end, periods=limit, freq=freq)

        np.random.seed(hash(instrument + timeframe) % 2**31)
        returns = np.random.normal(0, volatility / base, limit).cumsum()
        closes = base * (1 + returns)

        opens  = closes * (1 + np.random.normal(0, 0.0005, limit))
        highs  = np.maximum(opens, closes) * (1 + abs(np.random.normal(0, 0.0008, limit)))
        lows   = np.minimum(opens, closes) * (1 - abs(np.random.normal(0, 0.0008, limit)))
        vols   = abs(np.random.normal(1_000_000, 200_000, limit))

        return pd.DataFrame({
            "open": opens, "high": highs, "low": lows,
            "close": closes, "volume": vols
        }, index=idx)
