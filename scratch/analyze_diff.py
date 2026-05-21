import os

diff_path = r"e:\python\lh01\gold-quantification\scratch\app_diff.txt"

# Try reading as UTF-16LE, UTF-8, etc.
content = None
encodings = ['utf-16-le', 'utf-16', 'utf-8', 'gbk']
for enc in encodings:
    try:
        with open(diff_path, 'r', encoding=enc) as f:
            content = f.read()
        print(f"Successfully read diff file with encoding: {enc}")
        break
    except Exception as e:
        continue

if content is None:
    print("Could not read diff file with any encoding!")
    exit(1)

lines = content.splitlines()
deleted_lines = []
added_lines = []

for line in lines:
    if line.startswith('-') and not line.startswith('---'):
        deleted_lines.append(line[1:])
    elif line.startswith('+') and not line.startswith('+++'):
        added_lines.append(line[1:])

print(f"Total lines: {len(lines)}")
print(f"Deleted lines: {len(deleted_lines)}")
print(f"Added lines: {len(added_lines)}")

# Look for keywords in deleted lines
print("\nKeywords in deleted lines:")
keywords = ["AI 决策", "AI决策", "Agent Live", "脑电波", "智能对冲", "一键锁仓", "波动因子", "趋势因子", "主力资金", "AI 风险评估", "AI动能信心", "factor_row", "circular", "progress", "factors", "agent"]
for kw in keywords:
    count = sum(1 for line in deleted_lines if kw in line)
    print(f"  '{kw}': {count} occurrences")

# Print some of the deleted lines containing AI elements or UI components
print("\nDeleted lines sample containing UI components:")
sample_count = 0
for line in deleted_lines:
    if any(kw in line for kw in ["factor", "circular", "AI", "Agent", "brain", "决策", "脑电波"]):
        print(f"  {line.strip()}")
        sample_count += 1
        if sample_count >= 30:
            break
