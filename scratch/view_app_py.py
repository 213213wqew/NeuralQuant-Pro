import os

file_path = r"e:\python\lh01\gold-quantification\quant_app\ui\app.py"
if os.path.exists(file_path):
    size = os.path.getsize(file_path)
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    print(f"File exists. Size: {size} bytes, Line count: {len(lines)}")
    print("First 50 lines:")
    for idx, line in enumerate(lines[:50]):
        print(f"{idx+1}: {line}", end="")
else:
    print("File does not exist!")
