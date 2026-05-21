import time
import os
from quant_app.core.history_sync_service import history_sync_service
from quant_app.core.mt5_client import mt5_client
from quant_app.modules.strategies.grid_martingale_ma01.grid_ma_strategy import GridMartingaleMA01Strategy
from quant_app.modules.strategies.grid_martingale_ma02.grid_ma02_strategy import GridMartingaleMA02Strategy
from quant_app.core.logger import get_logger

logger = get_logger("Runner")

def main():
    # 1. 初始化 MT5 连接
    if not mt5_client.connect():
        logger.error("无法连接到 MT5 终端，程序退出。")
        return

    # 2. 准备策略参数
    strategy_name = os.getenv("ACTIVE_STRATEGY", "GridMartingaleMA02")
    active_preset = os.getenv("ACTIVE_PRESET", "")
    
    # 动态获取根目录（兼容打包环境，保持和以前一样的读取逻辑）
    base_dir = get_project_root()
    strategy_subdir = "grid_martingale_ma01" if strategy_name == "GridMartingaleMA01" else "grid_martingale_ma02"
    
    preset_path = None
    if active_preset:
        preset_path = os.path.join(
            base_dir,
            "modules",
            "strategies",
            strategy_subdir,
            "presets",
            active_preset,
        )
    
    # 3. 创建并启动策略
    history_sync_service.start()

    if strategy_name == "GridMartingaleMA02":
        strategy = GridMartingaleMA02Strategy(symbol="XAUUSD.c", preset_path=preset_path)
    else:
        strategy = GridMartingaleMA01Strategy(symbol="XAUUSD.c", preset_path=preset_path)
    
    strategy.start()

    logger.info("「模块化引擎」已启动，进入主循环...")

    # 4. 主循环迭代
    try:
        while True:
            strategy.run_iteration()
            time.sleep(1.5) # 1.5秒检查一次，保持响应性
    except KeyboardInterrupt:
        logger.info("用户终止程序")
    except Exception as e:
        logger.error(f"引擎崩溃: {e}")
    finally:
        strategy.stop()
        history_sync_service.stop()
        mt5_client.disconnect()

if __name__ == "__main__":
    main()
