import os
import json

dir_path = r"e:\python\lh01\gold-quantification\scratch\app_py_versions"
files = os.listdir(dir_path)
files.sort(key=lambda x: [int(s) if s.isdigit() else s for s in x.replace('_', ' ').split()])

print(f"Total files: {len(files)}")
for f in files:
    full_path = os.path.join(dir_path, f)
    size = os.path.getsize(full_path)
    print(f"File: {f}, size: {size} bytes")
