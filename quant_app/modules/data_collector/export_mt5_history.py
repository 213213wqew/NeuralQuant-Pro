from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import MetaTrader5 as mt5
import pandas as pd

from quant_app.core.logger import get_logger
from quant_app.core.mt5_client import mt5_client

logger = get_logger("ExportMT5History")


TF_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}


def export_history(
    *,
    symbol: str,
    timeframes: list[str],
    count_map: dict[str, int],
    out_dir: str,
) -> list[str]:
    if not mt5_client.ensure_connected():
        raise RuntimeError("MT5 not connected")

    target_dir = Path(out_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    saved_files: list[str] = []

    for tf_name in timeframes:
        tf_name = tf_name.upper()
        timeframe = TF_MAP.get(tf_name)
        if timeframe is None:
            logger.warning("skip unsupported timeframe: %s", tf_name)
            continue

        count = int(count_map.get(tf_name, 0) or 0)
        if count <= 0:
            logger.warning("skip timeframe %s because count <= 0", tf_name)
            continue

        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is None or len(rates) == 0:
            logger.warning("no rates for %s %s", symbol, tf_name)
            continue

        df = pd.DataFrame(rates)
        df["date"] = pd.to_datetime(df["time"], unit="s", errors="coerce")
        df = df[["date", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]]

        safe_symbol = symbol.replace(".", "_")
        filename = target_dir / f"{safe_symbol}_{tf_name}_{len(df)}_{stamp}.csv"
        df.to_csv(filename, index=False)
        saved_files.append(str(filename))
        logger.info("saved %s rows for %s %s -> %s", len(df), symbol, tf_name, filename)

    return saved_files


def main() -> None:
    parser = argparse.ArgumentParser(description="Export MT5 history for multiple timeframes to CSV.")
    parser.add_argument("--symbol", default="XAUUSD.c")
    parser.add_argument("--out-dir", default=r"E:\python\gold-quantification\data\mt5_history")
    parser.add_argument("--timeframes", nargs="+", default=["M1", "M5", "M30", "H1"])
    parser.add_argument("--count-m1", type=int, default=12000)
    parser.add_argument("--count-m5", type=int, default=6000)
    parser.add_argument("--count-m15", type=int, default=3000)
    parser.add_argument("--count-m30", type=int, default=2000)
    parser.add_argument("--count-h1", type=int, default=1500)
    parser.add_argument("--count-h4", type=int, default=800)
    parser.add_argument("--count-d1", type=int, default=500)
    args = parser.parse_args()

    count_map = {
        "M1": args.count_m1,
        "M5": args.count_m5,
        "M15": args.count_m15,
        "M30": args.count_m30,
        "H1": args.count_h1,
        "H4": args.count_h4,
        "D1": args.count_d1,
    }

    saved = export_history(
        symbol=args.symbol,
        timeframes=list(args.timeframes),
        count_map=count_map,
        out_dir=args.out_dir,
    )
    for item in saved:
        print(item)


if __name__ == "__main__":
    main()
