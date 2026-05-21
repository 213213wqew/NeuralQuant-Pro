from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


RULE_MAP = {
    "M5": "5min",
    "M15": "15min",
    "M30": "30min",
    "H1": "1h",
    "H4": "4h",
    "D1": "1d",
}


def load_m1_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "date" not in df.columns:
        raise ValueError("input csv missing 'date' column")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "tick_volume" not in df.columns:
        if "volume" in df.columns:
            df["tick_volume"] = pd.to_numeric(df["volume"], errors="coerce")
        else:
            df["tick_volume"] = 0.0
    df["tick_volume"] = pd.to_numeric(df["tick_volume"], errors="coerce").fillna(0.0)
    return df.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)


def resample_ohlc(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    rule = RULE_MAP[timeframe.upper()]
    indexed = df.set_index("date")
    out = indexed.resample(rule).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "tick_volume": "sum",
        }
    )
    out = out.dropna(subset=["open", "high", "low", "close"]).reset_index()
    return out


def save_resampled(input_csv: str, out_dir: str, timeframes: list[str]) -> list[str]:
    df = load_m1_csv(input_csv)
    source = Path(input_csv)
    stem = source.stem
    target_dir = Path(out_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    saved: list[str] = []
    for tf in timeframes:
        tf_upper = tf.upper()
        if tf_upper not in RULE_MAP:
            continue
        out = resample_ohlc(df, tf_upper)
        filename = target_dir / f"{stem}_{tf_upper}.csv"
        out.to_csv(filename, index=False)
        saved.append(str(filename))
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description="Resample M1 history CSV into higher timeframes.")
    parser.add_argument("--input-csv", required=True)
    parser.add_argument("--out-dir", default=r"E:\python\gold-quantification\data\mt5_history")
    parser.add_argument("--timeframes", nargs="+", default=["M5", "M30", "H1"])
    args = parser.parse_args()

    for item in save_resampled(args.input_csv, args.out_dir, list(args.timeframes)):
        print(item)


if __name__ == "__main__":
    main()
