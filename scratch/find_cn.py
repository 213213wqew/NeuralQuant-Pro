with open("e:/python/lh01/gold-quantification/quant_app/modules/panel/status_panel_bridge.py", "r", encoding="gbk", errors="ignore") as f:
    for i, line in enumerate(f, 1):
        if "_cn_downside_state" in line:
            print(f"Line {i}: {line.strip()}")
