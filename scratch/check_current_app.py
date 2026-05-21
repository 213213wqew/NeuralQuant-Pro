import os

file_path = r"e:\python\lh01\gold-quantification\quant_app\ui\app.py"
if os.path.exists(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    print("Successfully read current app.py!")
    print("Length:", len(content))
    print("Keywords search:")
    keywords = ["AI 决策", "AI决策", "Agent Live", "脑电波", "智能对冲", "一键锁仓", "波动因子", "趋势因子", "主力资金", "AI 风险评估", "AI动能信心"]
    for kw in keywords:
        print(f"  '{kw}': {kw in content}")
else:
    print("File does not exist!")
