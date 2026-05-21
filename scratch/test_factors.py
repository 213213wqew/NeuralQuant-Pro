import MetaTrader5 as mt5
import pandas as pd
import time

def main():
    if not mt5.initialize():
        print("Failed to initialize MT5")
        return
        
    symbol = "XAUUSD.c"
    # Try alternate symbols if XAUUSD.c is not found
    symbols_to_try = [symbol, "XAUUSD", "GOLD"]
    for sym in symbols_to_try:
        info = mt5.symbol_info(sym)
        if info is not None:
            symbol = sym
            break
            
    print(f"Using symbol: {symbol}")
    
    # Fetch 100 M1 bars
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 100)
    if rates is None or len(rates) == 0:
        print("Failed to fetch rates:", mt5.last_error())
        mt5.shutdown()
        return
        
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.columns = [c.lower() for c in df.columns]
    
    # Calculate volatility factor
    df_slice = df.tail(20)
    high_low_ranges = df_slice['high'] - df_slice['low']
    avg_range = high_low_ranges.mean()
    latest_close = df_slice['close'].iloc[-1]
    
    # M1 scale is 4000.0 in app.py
    scale = 4000.0
    vol_ratio = (avg_range / latest_close) * scale
    volatility_factor = max(5.0, min(95.0, vol_ratio * 100.0))
    
    # Calculate flow factor
    buy_vols = []
    total_vols = []
    for _, row in df_slice.iterrows():
        vol = float(row.get('tick_volume', row.get('volume', 0.0)))
        close_p = float(row.get('close', 0.0))
        open_p = float(row.get('open', 0.0))
        high_p = float(row.get('high', 0.0))
        low_p = float(row.get('low', 0.0))
        
        if high_p > low_p:
            multiplier = (close_p - low_p) / (high_p - low_p)
        else:
            multiplier = 0.5
        
        buy_vols.append(vol * multiplier)
        total_vols.append(vol)
        
    sum_buy_vol = sum(buy_vols)
    sum_total_vol = sum(total_vols)
    
    if sum_total_vol > 0:
        flow_ratio = sum_buy_vol / sum_total_vol
        flow_factor = 10.0 + flow_ratio * 88.0
    else:
        flow_factor = 50.0
        
    print(f"Average M1 range: {avg_range:.4f}")
    print(f"Latest close: {latest_close:.4f}")
    print(f"Volatility Ratio * 100: {vol_ratio * 100.0:.2f}%")
    print(f"Calculated Volatility Factor (capped): {volatility_factor:.2f}%")
    print(f"Sum Buy Volume: {sum_buy_vol:.2f}")
    print(f"Sum Total Volume: {sum_total_vol:.2f}")
    print(f"Flow Ratio: {flow_ratio:.4f}")
    print(f"Calculated Flow Factor: {flow_factor:.2f}%")
    
    mt5.shutdown()

if __name__ == "__main__":
    main()
