import MetaTrader5 as mt5
import os
import sys
import time
import threading
from datetime import datetime, timedelta
from quant_app.core.logger import get_logger

logger = get_logger("MT5Client")

class MT5Client:
    def __init__(self):
        self.connected = False
        # 修正路径：现在在 core/ 目录下，向上两级到达 quant_app/
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) 
        self.runtime_root = self._runtime_root()
        self.env_path = os.path.join(self.runtime_root, ".env")
        self.config_path = os.path.join(self.runtime_root, "config.json")
        self.mt5_path = self.load_config()
        self.last_initialized_path = None # 记录最近一次成功的路径
        self.lock = threading.RLock()

    def _runtime_root(self):
        if getattr(sys, "frozen", False):
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            if self._is_writable_dir(exe_dir):
                return exe_dir
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                exe_name = os.path.splitext(os.path.basename(sys.executable))[0] or "NeuralQuantPro"
                root = os.path.join(appdata, "NeuralQuantPro", exe_name)
                os.makedirs(root, exist_ok=True)
                return root
        return os.path.dirname(self.base_dir)

    @staticmethod
    def _is_writable_dir(path):
        try:
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, ".neuralquant_write_test")
            with open(probe, "w", encoding="utf-8") as handle:
                handle.write("ok")
            os.remove(probe)
            return True
        except Exception:
            return False

    def load_config(self):
        """从 .env 文件或旧版 config 读取路径"""
        try:
            if os.path.exists(self.env_path):
                with open(self.env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.startswith("MT5_PATH="):
                            path = line.split("MT5_PATH=")[1].strip()
                            path = path.strip('"').strip("'")
                            if os.path.exists(path):
                                logger.info(f"从 .env 成功加载 MT5 路径: {path}")
                                return path
            
            if os.path.exists(self.config_path):
                import json
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    path = config.get("mt5_path")
                    if path and os.path.exists(path):
                        return path
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
        return None

    def connect(self):
        """建立 MT5 链接"""
        with self.lock:
            try:
                self.mt5_path = self.load_config()
                
                if self.connected and self.mt5_path == self.last_initialized_path:
                    if mt5.terminal_info() is not None:
                        return True
                
                logger.info(f"正在建立链路, 路径: {self.mt5_path}")
                if not self.mt5_path or not os.path.exists(self.mt5_path):
                    logger.error(f"物理路径不可达: {self.mt5_path}")
                    self.connected = False
                    return False
                
                if self.last_initialized_path is not None and self.mt5_path != self.last_initialized_path:
                    logger.warning("路径变更，正在释放旧资源...")
                    mt5.shutdown()
                
                success = mt5.initialize(path=self.mt5_path)
                if not success:
                    err = mt5.last_error()
                    logger.error(f"MT5 握手失败! 错误码: {err}")
                    self.connected = False
                    return False
                    
                self.connected = True
                self.last_initialized_path = self.mt5_path
                logger.info("MT5 链路已同步")
                return True
            except Exception as e:
                logger.error(f"连接异常: {e}")
                self.connected = False
                return False

    def disconnect(self):
        """主动断开 MT5 链路"""
        with self.lock:
            mt5.shutdown()
            self.connected = False
            self.last_initialized_path = None
            logger.info("MT5 链路已释放")

    def ensure_connected(self):
        """保活检查"""
        if not self.connected:
            return self.connect()
            
        if mt5.terminal_info() is None:
            logger.warning("检测到 MT5 终端断开，尝试恢复...")
            self.connected = False
            return self.connect()
        return True

    # ... 其余方法保持逻辑不变，但将 print 替换为 logger ...
    def get_account_stat(self):
        if not self.ensure_connected(): return None
        with self.lock:
            info = mt5.account_info()
            if not info: return None
            return {
                "login": info.login, "server": info.server,
                "balance": info.balance, "equity": info.equity,
                "profit": info.profit, "margin": info.margin,
                "margin_free": info.margin_free,
                "margin_level": info.margin_level if hasattr(info, 'margin_level') else 0,
                "currency": info.currency,
                "trade_mode": info.trade_mode,
                "trade_allowed": mt5.terminal_info().trade_allowed if mt5.terminal_info() else False
            }

    def get_market_data(self, symbol="XAUUSD.c"):
        if not self.ensure_connected(): return None
        with self.lock:
            tick = mt5.symbol_info_tick(symbol)
            if tick:
                return {
                    "bid": tick.bid, "ask": tick.ask, "last": tick.last,
                    "time": tick.time, "symbol": symbol
                }
        return None

    def get_history_bars(self, symbol="XAUUSD.c", timeframe=mt5.TIMEFRAME_M1, count=150):
        if not self.ensure_connected(): return []
        with self.lock:
            actual_count = count
            if timeframe == mt5.TIMEFRAME_H1:
                actual_count = 100
            rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, actual_count)
            if rates is None: return []
            
            result = []
            for r in rates:
                result.append({
                    "time": int(r['time']),
                    "open": float(r['open']), "high": float(r['high']),
                    "low": float(r['low']), "close": float(r['close'])
                })
            return result

    def get_positions(self, symbol=None):
        if not self.ensure_connected(): return []
        with self.lock:
            if symbol:
                positions = mt5.positions_get(symbol=symbol)
            else:
                positions = mt5.positions_get()
            if not positions: return []
            result = []
            for p in positions:
                result.append({
                    "ticket": p.ticket, "symbol": p.symbol, "volume": p.volume,
                    "type": "BUY" if p.type == 0 else "SELL",
                    "price_open": p.price_open,
                    "price_current": p.price_current,
                    "sl": p.sl, "tp": p.tp,
                    "profit": p.profit,
                    # 部分 MT5 Python 绑定里 TradePosition 无 commission 字段，用 getattr 与 UI/篮子口径一致
                    "swap": float(getattr(p, "swap", 0.0) or 0.0),
                    "commission": float(getattr(p, "commission", 0.0) or 0.0),
                    "magic": p.magic,
                    "comment": p.comment,
                    "time_raw": p.time,
                    "time": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(p.time))
                })
            return result

    def get_trade_history(self, days=90):
        if not self.ensure_connected(): return None
        with self.lock:
            from_date = datetime.now() - timedelta(days=days)
            to_date = datetime.now()
            
            deals = mt5.history_deals_get(from_date, to_date)
            if deals is None or len(deals) == 0:
                return {"deals": [], "summary": {"profit": 0.0, "deposit": 0.0, "withdrawal": 0.0}}
            
            history_list = []
            summary = {"profit": 0.0, "deposit": 0.0, "withdrawal": 0.0}
            
            for d in deals:
                d_dict = d._asdict()
                if d_dict['type'] == mt5.DEAL_TYPE_BALANCE:
                    if d_dict['profit'] >= 0: summary['deposit'] += d_dict['profit']
                    else: summary['withdrawal'] += abs(d_dict['profit'])
                    continue

                net_profit = d_dict['profit'] + d_dict['commission'] + d_dict['swap']
                summary['profit'] += net_profit
                
                if d_dict['entry'] in [1, 2, 3]:
                    deal_type = "Buy" if d_dict['type'] == mt5.DEAL_TYPE_BUY else "Sell" if d_dict['type'] == mt5.DEAL_TYPE_SELL else "Other"
                    history_list.append({
                        "ticket": d_dict['ticket'], "symbol": d_dict['symbol'],
                        "time": datetime.fromtimestamp(d_dict['time']).strftime('%Y.%m.%d %H:%M:%S'),
                        "time_raw": d_dict['time'],
                        "type": deal_type, "volume": d_dict['volume'], "price": d_dict['price'],
                        "profit": round(net_profit, 2), "comment": d_dict['comment']
                    })
            
            history_list.sort(key=lambda x: x['time_raw'], reverse=True)
            return {"deals": history_list, "summary": summary}

    def _get_broker_time(self):
        # 1. 尝试获取交易品种的最新 tick 时间作为平台时间
        symbol = os.environ.get("TRADE_SYMBOL", "XAUUSD.c")
        tick = mt5.symbol_info_tick(symbol)
        if tick:
            return tick.time
        # 2. 尝试默认黄金品种
        if symbol != "XAUUSD.c":
            tick = mt5.symbol_info_tick("XAUUSD.c")
            if tick:
                return tick.time
        # 3. 尝试 EURUSD
        tick = mt5.symbol_info_tick("EURUSD")
        if tick:
            return tick.time
        # 4. 兜底返回本地系统时间戳
        import time
        return int(time.time())

    def get_today_profit(self):
        if not self.ensure_connected(): return 0.0
        with self.lock:
            from datetime import datetime, timezone
            broker_time_ts = self._get_broker_time()
            # MT5 接口时间戳即为平台本地时间对应的 UTC 时间表示
            broker_now = datetime.utcfromtimestamp(broker_time_ts)
            
            # 今日 00:00:00 平台时间
            broker_today_start = datetime(broker_now.year, broker_now.month, broker_now.day, 0, 0, 0)
            today_start_ts = int(broker_today_start.replace(tzinfo=timezone.utc).timestamp())
            
            deals = mt5.history_deals_get(today_start_ts, broker_time_ts + 3600)
            if deals is None or len(deals) == 0:
                return 0.0
            
            today_profit = 0.0
            for d in deals:
                d_dict = d._asdict()
                if d_dict['type'] == mt5.DEAL_TYPE_BALANCE:
                    continue
                # 净利润 = 盈亏 + 手续费 + 库存费
                net_profit = d_dict['profit'] + d_dict['commission'] + d_dict['swap']
                today_profit += net_profit
            return round(today_profit, 2)

    def get_market_exposure(self):
        """获取全品种市场敞口统计"""
        positions = self.get_positions()
        if not positions:
            return []
        
        exposure = {}
        for p in positions:
            symbol = p['symbol']
            if symbol not in exposure:
                exposure[symbol] = {'asset': symbol, 'volume': 0.0, 'profit': 0.0, 'rate': p['price_current']}
            
            # 买单为正，卖单为负
            vol = p['volume'] if p['type'] == "BUY" else -p['volume']
            exposure[symbol]['volume'] += vol
            exposure[symbol]['profit'] += p['profit']
            exposure[symbol]['rate'] = p['price_current']
            
        return list(exposure.values())

mt5_client = MT5Client()
