import flet as ft
import sys
import os

# 确保 quant_app 及其 backend 目录在搜索路径中
if getattr(sys, 'frozen', False):
    # 打包后的环境
    root_dir = sys._MEIPASS
else:
    # 开发运行环境
    root_dir = os.path.dirname(os.path.abspath(__file__))

quant_app_dir = os.path.join(root_dir, "quant_app")
ui_dir = os.path.join(quant_app_dir, "ui")

for p in (root_dir, quant_app_dir, ui_dir):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from quant_app.ui.app import main
except ModuleNotFoundError:
    try:
        from ui.app import main
    except ModuleNotFoundError:
        from app import main

if __name__ == "__main__":
    # 以桌面 App 模式启动 (适配 0.84.0 规范)
    ft.run(main)
