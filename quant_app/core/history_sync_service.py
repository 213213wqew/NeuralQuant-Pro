from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import MetaTrader5 as mt5
import pandas as pd

from quant_app.core.logger import get_logger
from quant_app.core.mt5_client import mt5_client

logger = get_logger("HistorySyncService")


class HistorySyncService:
    def __init__(self):
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._started = False
        self.symbol = os.getenv("TRADE_SYMBOL", "XAUUSD.c")
        self.root_dir = Path(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self.mt5_dir = self.root_dir / "data" / "mt5_history"
        self.update_symbol(self.symbol)
        self.interval_sec = 45.0
        self.fetch_count = 12000
        self.fetch_count_m15 = 12000
        self.fetch_count_m5 = 12000
        self.fetch_count_m30 = 8000
        self.fetch_count_h1 = 6000
        self.fetch_count_d1 = 3000
        self._last_write_at = 0.0
        self.min_write_gap_sec = 20.0

    def update_symbol(self, new_symbol: str):
        with self._lock:
            self.symbol = new_symbol
            prefix = new_symbol.lower().replace(".", "_")
            if new_symbol == "XAUUSD.c":
                name = "gold"
            else:
                name = prefix
            self.m1_path = self.root_dir / f"{name}_m1_history.csv"
            self.m15_path = self.mt5_dir / f"{name}_m1_history_M15.csv"
            self.m5_path = self.mt5_dir / f"{name}_m1_history_M5.csv"
            self.m30_path = self.mt5_dir / f"{name}_m1_history_M30.csv"
            self.h1_path = self.mt5_dir / f"{name}_m1_history_H1.csv"
            self.d1_path = self.mt5_dir / f"{name}_m1_history_D1.csv"

    def start(self):
        with self._lock:
            if self._started and self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="HistorySyncService")
            self._thread.start()
            self._started = True
            logger.info("history sync service started")

    def stop(self):
        with self._lock:
            self._stop_event.set()
            self._started = False
            logger.info("history sync service stopping")

    def sync_now(self):
        try:
            self._sync_once(force=True)
        except Exception as exc:
            logger.warning("history sync_now failed: %s", exc)

    def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                self._sync_once(force=False)
            except Exception as exc:
                logger.warning("history background sync failed: %s", exc)
            self._stop_event.wait(self.interval_sec)

    def _sync_once(self, force: bool):
        now = time.time()
        if not force and now - self._last_write_at < self.min_write_gap_sec:
            return
        if not mt5_client.ensure_connected():
            return

        m1_df = self._fetch_timeframe_df(mt5.TIMEFRAME_M1, self.fetch_count)
        m15_df = self._fetch_timeframe_df(mt5.TIMEFRAME_M15, self.fetch_count_m15)
        m5_df = self._fetch_timeframe_df(mt5.TIMEFRAME_M5, self.fetch_count_m5)
        m30_df = self._fetch_timeframe_df(mt5.TIMEFRAME_M30, self.fetch_count_m30)
        h1_df = self._fetch_timeframe_df(mt5.TIMEFRAME_H1, self.fetch_count_h1)
        d1_df = self._fetch_timeframe_df(mt5.TIMEFRAME_D1, self.fetch_count_d1)

        if m1_df is None or len(m1_df) == 0:
            return

        merged_m1 = self._merge_with_existing(self.m1_path, m1_df)
        merged_m15 = self._merge_with_existing(self.m15_path, m15_df) if m15_df is not None and len(m15_df) > 0 else None
        merged_m5 = self._merge_with_existing(self.m5_path, m5_df) if m5_df is not None and len(m5_df) > 0 else None
        merged_m30 = self._merge_with_existing(self.m30_path, m30_df) if m30_df is not None and len(m30_df) > 0 else None
        merged_h1 = self._merge_with_existing(self.h1_path, h1_df) if h1_df is not None and len(h1_df) > 0 else None
        merged_d1 = self._merge_with_existing(self.d1_path, d1_df) if d1_df is not None and len(d1_df) > 0 else None

        self._write_all(merged_m1, merged_m15, merged_m5, merged_m30, merged_h1, merged_d1)
        self._last_write_at = now

    def _fetch_timeframe_df(self, timeframe: int, count: int) -> pd.DataFrame | None:
        rates = mt5.copy_rates_from_pos(self.symbol, timeframe, 0, count)
        if rates is None or len(rates) == 0:
            return None
        fresh = pd.DataFrame(rates)
        fresh["date"] = pd.to_datetime(fresh["time"], unit="s", errors="coerce")
        fresh = fresh[["date", "open", "high", "low", "close", "tick_volume"]]
        fresh = fresh.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)
        return fresh

    def _merge_with_existing(self, path: Path, fresh: pd.DataFrame) -> pd.DataFrame:
        if path.exists():
            try:
                old = pd.read_csv(path)
                old["date"] = pd.to_datetime(old["date"], errors="coerce")
                for col in ["open", "high", "low", "close", "tick_volume"]:
                    if col in old.columns:
                        old[col] = pd.to_numeric(old[col], errors="coerce")
                old = old.dropna(subset=["date", "open", "high", "low", "close"])
                combined = pd.concat([old[["date", "open", "high", "low", "close", "tick_volume"]], fresh], ignore_index=True)
            except Exception:
                combined = fresh.copy()
        else:
            combined = fresh.copy()
        combined = combined.drop_duplicates(subset=["date"], keep="last").sort_values("date").reset_index(drop=True)
        return combined

    def _write_all(
        self,
        m1_df: pd.DataFrame,
        m15_df: pd.DataFrame | None,
        m5_df: pd.DataFrame | None,
        m30_df: pd.DataFrame | None,
        h1_df: pd.DataFrame | None,
        d1_df: pd.DataFrame | None,
    ):
        self.mt5_dir.mkdir(parents=True, exist_ok=True)
        m1_df.to_csv(self.m1_path, index=False)
        if m15_df is not None:
            m15_df.to_csv(self.m15_path, index=False)
        if m5_df is not None:
            m5_df.to_csv(self.m5_path, index=False)
        if m30_df is not None:
            m30_df.to_csv(self.m30_path, index=False)
        if h1_df is not None:
            h1_df.to_csv(self.h1_path, index=False)
        if d1_df is not None:
            d1_df.to_csv(self.d1_path, index=False)


history_sync_service = HistorySyncService()
