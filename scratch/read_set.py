import sys
import os

# Add the project root to sys.path
sys.path.append(r'e:\python\量化')

try:
    from quant_app.backend.utils.config_loader import ConfigLoader
    path = r'e:\python\量化\quant_app\backend\strategies\presets\保守1111(1)(1).set'
    data = ConfigLoader.load_set_file(path)
    print("--- PARSED DATA ---")
    for k, v in data.items():
        print(f"{k}={v}")
except Exception as e:
    print(f"Error: {e}")
