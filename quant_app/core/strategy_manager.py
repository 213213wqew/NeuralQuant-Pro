import time
import threading
import os
from quant_app.core.logger import get_logger
from quant_app.core.history_sync_service import history_sync_service
from quant_app.core.mt5_client import mt5_client
from quant_app.modules.strategies.grid_martingale_ma01.grid_ma_strategy import GridMartingaleMA01Strategy
from quant_app.modules.strategies.grid_martingale_ma02.grid_ma02_strategy import GridMartingaleMA02Strategy
from quant_app.modules.strategies.grid_martingale_ma04.grid_ma_strategy04 import GridMartingaleMA04Strategy
from quant_app.modules.strategies.steady_worker.steady_worker import SteadyWorker
from quant_app.modules.ai.auto_trainer import ai_trainer

logger = get_logger("ModularRunner")

class StrategyManager:
    def __init__(self):
        self.current_strategy = None
        self.is_running = False
        self.stop_event = threading.Event()
        self.thread = None
        
        # 优先从 .env 加载品种，默认为黄金
        from quant_app.core.mt5_client import mt5_client
        self.symbol = os.getenv("TRADE_SYMBOL", "XAUUSD.c")
        
        self.strategy_name = os.getenv("ACTIVE_STRATEGY", "GridMartingaleMA02")
        self.status_message = "策略待命中"
        self.current_config_file = None

    def set_strategy(self, name, set_file=None):
        """动态加载模块化策略类"""
        try:
            was_running = self.is_running
            previous_strategy = self.current_strategy
            next_strategy = None
            next_config_file = None

            if name == "GridMartingaleMA01":
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                preset_dir = os.path.join(base_dir, "modules", "strategies", "grid_martingale_ma01", "presets")

                final_set_path = None
                if set_file:
                    potential_path = os.path.join(preset_dir, set_file)
                    if os.path.exists(potential_path):
                        final_set_path = potential_path

                if not final_set_path:
                    env_path = mt5_client.env_path
                    if os.path.exists(env_path):
                        with open(env_path, 'r', encoding='utf-8') as f:
                            for line in f:
                                if line.startswith("ACTIVE_PRESET="):
                                    env_preset = line.split("ACTIVE_PRESET=")[1].strip().strip('"').strip("'")
                                    potential_path = os.path.join(preset_dir, env_preset)
                                    if os.path.exists(potential_path):
                                        final_set_path = potential_path

                next_config_file = os.path.basename(final_set_path) if final_set_path else None
                next_strategy = GridMartingaleMA01Strategy(symbol=self.symbol, preset_path=final_set_path)

            elif name == "GridMartingaleMA02":
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                preset_dir = os.path.join(base_dir, "modules", "strategies", "grid_martingale_ma02", "presets")

                final_set_path = None
                if set_file:
                    potential_path = os.path.join(preset_dir, set_file)
                    if os.path.exists(potential_path):
                        final_set_path = potential_path

                if not final_set_path:
                    env_path = mt5_client.env_path
                    if os.path.exists(env_path):
                        with open(env_path, 'r', encoding='utf-8') as f:
                            for line in f:
                                if line.startswith("ACTIVE_PRESET="):
                                    env_preset = line.split("ACTIVE_PRESET=")[1].strip().strip('"').strip("'")
                                    potential_path = os.path.join(preset_dir, env_preset)
                                    if os.path.exists(potential_path):
                                        final_set_path = potential_path

                next_config_file = os.path.basename(final_set_path) if final_set_path else None
                next_strategy = GridMartingaleMA02Strategy(symbol=self.symbol, preset_path=final_set_path)

            elif name == "GridMartingaleMA04":
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                preset_dir = os.path.join(base_dir, "modules", "strategies", "grid_martingale_ma04", "presets")

                final_set_path = None
                if set_file:
                    potential_path = os.path.join(preset_dir, set_file)
                    if os.path.exists(potential_path):
                        final_set_path = potential_path

                if not final_set_path:
                    env_path = mt5_client.env_path
                    if os.path.exists(env_path):
                        with open(env_path, 'r', encoding='utf-8') as f:
                            for line in f:
                                if line.startswith("ACTIVE_PRESET="):
                                    env_preset = line.split("ACTIVE_PRESET=")[1].strip().strip('"').strip("'")
                                    potential_path = os.path.join(preset_dir, env_preset)
                                    if os.path.exists(potential_path):
                                        final_set_path = potential_path

                next_config_file = os.path.basename(final_set_path) if final_set_path else None
                next_strategy = GridMartingaleMA04Strategy(symbol=self.symbol, preset_path=final_set_path)

            elif name == "SteadyWorker":
                next_strategy = SteadyWorker(symbol=self.symbol)
                next_config_file = None

            else:
                logger.error(f"未知策略类型: {name}")
                return False
            
            if was_running and next_strategy:
                next_strategy.start()
                if previous_strategy:
                    previous_strategy.stop()

            self.current_strategy = next_strategy
            self.current_config_file = next_config_file
            self.strategy_name = name
            if was_running:
                self.status_message = f"策略运行中: {self.strategy_name}"
            logger.info(f"策略已切换为: {name} ({self.current_config_file or '默认配置'})")
            return True
        except Exception as e:
            logger.exception(f"加载策略 {name} 失败: {e}")
            return False

    def start(self):
        if self.is_running: return
        
        if not mt5_client.connected:
            mt5_client.connect()

        if not self.current_strategy:
            self.set_strategy(self.strategy_name)

        if not self.current_strategy:
            logger.error("无法启动：策略未就绪")
            return

        self.is_running = True
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.thread.start()
        history_sync_service.start()
        
        # 启动 AI 自动进化引擎
        try:
            ai_trainer.start()
        except Exception as e:
            logger.error(f"AI 自动教练启动失败: {e}")
            
        self.current_strategy.start()
        self.status_message = f"策略运行中: {self.strategy_name}"
        logger.info(f"模块化策略引擎已启动: {self.strategy_name}")

    def stop(self):
        self.is_running = False
        self.stop_event.set()
        if self.current_strategy:
            self.current_strategy.stop()
        history_sync_service.stop()
        self.thread = None
        self.status_message = "策略已停止"
        logger.info("模块化策略引擎已停止")

    def stop_and_clear(self, symbol=None):
        """强制停止并极速平仓（紧急按钮/停止策略）"""
        self.stop()
        
        # 安全保护：如果全局对冲管理器处于“锁仓”状态，严禁清场平仓，必须保留锁仓状态供解仓使用
        try:
            from quant_app.modules.hedge.hedge_manager import hedge_manager
            if hedge_manager.get_state().is_locked:
                logger.warning("当前处于全局对冲锁仓状态下停止策略，安全跳过平仓清场，保留所有锁仓头寸。")
                return {"count": 0, "success": True}
        except Exception as ex:
            logger.error(f"检查对冲锁仓状态失败: {ex}")
        
        from quant_app.core.order_executor import order_executor
        
        # 如果指定了品种 and 策略，使用极速批量接口
        target_symbol = symbol if symbol else self.symbol
        magic = getattr(self.current_strategy.config, "InpMagic", None) if self.current_strategy else None
        
        if target_symbol and magic:
            logger.warning(f"正在执行【极速】强制平仓，品种: {target_symbol}, Magic: {magic}")
            res = order_executor.close_all_fast(target_symbol, magic)
            count = res.get("count", 0)
            
            # 保底逻辑：检查是否还有漏网之鱼
            time.sleep(0.5)
            remaining = mt5_client.get_positions(symbol=target_symbol)
            for p in remaining:
                if p.get('magic') == magic:
                    logger.warning(f"发现漏网订单 {p['ticket']}，正在执行二次清场...")
                    order_executor.close_position(p['ticket'])
                    count += 1
        else:
            # 备选方案：如果没有 magic，则使用并发平仓
            positions = mt5_client.get_positions(symbol=target_symbol)
            count = 0
            if positions:
                logger.warning(f"正在执行并发强制平仓，涉及订单数: {len(positions)}")
                for p in positions:
                    order_executor.close_position(p['ticket'])
                    count += 1
        
        logger.warning(f"极速清场完成，累计处理 {count} 笔平仓指令")
        return {"count": count, "success": True}

    def _worker_loop(self):
        while not self.stop_event.is_set() and self.is_running:
            try:
                # 核心风控挂起：若当前全局对冲管理器已锁仓，必须挂起正常网格策略，防范策略开仓破坏锁仓
                is_locked_status = False
                try:
                    from quant_app.modules.hedge.hedge_manager import hedge_manager
                    is_locked_status = hedge_manager.get_state().is_locked
                except Exception:
                    pass

                if is_locked_status:
                    self.status_message = "策略挂起中(对冲锁仓生效)"
                    time.sleep(1.0)
                    continue

                if self.current_strategy:
                    self.current_strategy.run_iteration()
                # 恢复高频心跳（0.5秒），防止 MT5 端 3 秒超时判定导致显示“未连接”
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"策略运行循环异常: {e}")
                time.sleep(10)

strategy_runner = StrategyManager()
