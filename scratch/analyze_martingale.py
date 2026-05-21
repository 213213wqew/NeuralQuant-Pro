
import re
import sys

def parse_mt5_report(file_path):
    with open(file_path, 'r', encoding='utf-16le') as f:
        content = f.read()

    row_pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL)
    td_pattern = re.compile(r'<td[^>]*>(.*?)</td>', re.DOTALL)
    
    trades = []
    rows = row_pattern.findall(content)
    
    for row in rows:
        tds = [re.sub(r'<[^>]+>', '', t).strip() for t in td_pattern.findall(row)]
        if len(tds) >= 14:
            open_time = tds[0]
            if re.match(r'\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}', open_time):
                try:
                    trade = {
                        'open_time': open_time,
                        'ticket': tds[1],
                        'symbol': tds[2],
                        'type': tds[3],
                        'comment': tds[4],
                        'volume': float(tds[5].replace(' ', '')),
                        'open_price': float(tds[6].replace(' ', '')),
                        'close_time': tds[9],
                        'close_price': float(tds[10].replace(' ', '')),
                        'commission': float(tds[11].replace(' ', '')),
                        'swap': float(tds[12].replace(' ', '')),
                        'profit': float(tds[13].replace(' ', ''))
                    }
                    trades.append(trade)
                except ValueError:
                    continue
    return trades

def analyze_baskets(trades):
    if not trades:
        return []
    trades.sort(key=lambda x: x['close_time'])
    baskets = []
    current_basket = []
    for trade in trades:
        if not current_basket:
            current_basket.append(trade)
        else:
            if trade['close_time'] == current_basket[-1]['close_time']:
                current_basket.append(trade)
            else:
                baskets.append(current_basket)
                current_basket = [trade]
    if current_basket:
        baskets.append(current_basket)
    return baskets

if __name__ == '__main__':
    report_file = r'e:\python\量化\ReportHistory-4002021 copy.html'
    all_trades = parse_mt5_report(report_file)
    
    print(f"Total trades: {len(all_trades)}")
    
    baskets = analyze_baskets(all_trades)
    print(f"Total baskets: {len(baskets)}")
    
    # Sort baskets by order count to find the most stressed periods
    baskets.sort(key=lambda x: len(x), reverse=True)
    
    print("\n--- Top 10 Most Stressed Baskets (Max Levels) ---")
    for i, basket in enumerate(baskets[:10]):
        net = sum(t['profit'] + t['commission'] + t['swap'] for t in basket)
        max_lot = max(t['volume'] for t in basket)
        print(f"Top {i+1} | {basket[0]['close_time']} | {basket[0]['symbol']} | Orders: {len(basket)} | Max Lot: {max_lot:.2f} | Net: {net:.2f}")

    # Weekly profit
    # (Optional: group by date)
