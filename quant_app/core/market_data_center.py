from __future__ import annotations

import threading
import time

import MetaTrader5 as mt5
import pandas as pd

from quant_app.core.logger import get_logger
from quant_app.core.mt5_client import mt5_client

logger = get_logger("MarketDataCenter")


class MarketDataCenter:
    """Shared real-time market data hub.

    One place fetches the latest bars, then the rest of the system reuses the
    same in-memory data instead of calling MT5 repeatedly from scattered
    modules.
    """

    _TF_MAP = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }

    def __init__(self):
        self._lock = threading.RLock()
        self._cache: dict[tuple, tuple[float, pd.DataFrame]] = {}

    def get_market_data(
        self,
        symbol: str,
        timeframe_str: str,
        count: int = 100,
        start_pos: int = 0,
        cache_ttl: float = 1.0,
    ) -> pd.DataFrame | None:
        raw = self._get_rates_df(symbol, timeframe_str, count=count, start_pos=start_pos, cache_ttl=cache_ttl)
        if raw is None or raw.empty:
            return None
        df = raw.copy(deep=True)
        df.rename(
            columns={
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "tick_volume": "Volume",
            },
            inplace=True,
        )
        return df

    def get_analysis_data(
        self,
        symbol: str,
        count: int = 300,
        cache_ttl: float = 0.8,
    ) -> pd.DataFrame | None:
        return self._get_rates_df(symbol, "M1", count=count, start_pos=0, cache_ttl=cache_ttl)

    def get_multi_timeframe_context(
        self,
        symbol: str = "XAUUSD.c",
        target_tf_str: str = "M1",
        cache_ttl: float = 1.0,
    ):
        df_h1 = self._get_rates_df(symbol, "H1", count=72, start_pos=0, cache_ttl=cache_ttl)
        df_target = self._get_rates_df(symbol, target_tf_str, count=60, start_pos=0, cache_ttl=cache_ttl)
        if df_h1 is None or df_target is None:
            return None, None
        return df_target.copy(deep=True), df_h1.copy(deep=True)

    def _get_rates_df(
        self,
        symbol: str,
        timeframe_str: str,
        *,
        count: int,
        start_pos: int,
        cache_ttl: float,
    ) -> pd.DataFrame | None:
        tf_name = str(timeframe_str or "M1").upper()
        tf = self._TF_MAP.get(tf_name)
        if tf is None:
            logger.warning("unknown timeframe '%s', fallback to M1", timeframe_str)
            tf_name = "M1"
            tf = mt5.TIMEFRAME_M1

        key = (symbol, tf_name, int(count), int(start_pos))
        now = time.time()
        with self._lock:
            cached = self._cache.get(key)
            if cached and now - cached[0] <= max(0.0, float(cache_ttl)):
                return cached[1].copy(deep=True)

        if not mt5_client.ensure_connected():
            return None

        rates = mt5.copy_rates_from_pos(symbol, tf, int(start_pos), int(count))
        if rates is None or len(rates) == 0:
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        with self._lock:
            self._cache[key] = (now, df)
        return df.copy(deep=True)


market_data_center = MarketDataCenter()

