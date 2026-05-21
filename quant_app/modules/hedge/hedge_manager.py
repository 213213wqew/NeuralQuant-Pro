"""
quant_app/modules/hedge/hedge_manager.py

对冲风控业务引擎 — 职责分离层
=====================================
本模块是锁仓/解仓/一键全平的唯一业务逻辑中心。
前端 UI (app.py) 只调用本模块的公开方法，不包含任何 MT5 交易逻辑。

状态持久化：
  程序关闭后锁仓状态不丢失，存储于 quant_app/brain/hedge_state.json
  下次启动时自动恢复，UI 可立即渲染正确的锁仓状态标识。

架构层次：
  UI (app.py)
    └─> HedgeManager  (本文件)
          └─> OrderExecutor (core/order_executor.py)
                └─> MetaTrader5 API
"""

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import MetaTrader5 as mt5

from quant_app.core.logger import get_logger
from quant_app.core.mt5_client import mt5_client
from quant_app.core.order_executor import order_executor

logger = get_logger("HedgeManager")

# 状态文件路径：与 quant_app 同级的 brain 目录（已有持久化惯例）
_STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "brain",
    "hedge_state.json",
)


@dataclass
class HedgeState:
    """对冲锁仓状态的完整快照，序列化到 JSON 文件持久化。"""

    is_locked: bool = False
    symbol: str = ""
    hedge_ticket: Optional[int] = None        # MT5 对冲单 ticket 号
    hedge_direction: str = ""                 # "BUY" 或 "SELL"
    hedge_volume: float = 0.0                 # 对冲手数
    net_exposure_at_lock: float = 0.0         # 锁仓时的净敞口（用于记录）
    lock_time: str = ""                       # ISO 时间字符串
    active_unlock_strategy: Optional[str] = None  # 当前激活的解仓策略名
    
    # 策略 2/3/4 新增辅助字段
    offset_used_profit: float = 0.0           # 盈利冲抵已消耗的利润
    lock_price: float = 0.0                   # 锁仓基准价格
    highest_price_since_breakout: float = 0.0 # 突破后记录最高价
    lowest_price_since_breakout: float = 0.0  # 突破后记录最低价
    breakout_direction: Optional[str] = None  # "UP" 或 "DOWN"
    dca_level: int = 0                        # DCA 网格层数
    last_dca_price: float = 0.0               # 最近一次 DCA 网格价格

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "HedgeState":
        # 忽略未知字段，保证向后兼容
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


class HedgeManager:
    """
    对冲风控管理器（单例）。

    公开方法（供 UI 调用）：
      lock(symbol)              → dict  一键锁仓
      unlock(symbol, strategy)  → dict  智能解仓
      close_all(symbol)         → dict  一键全平
      get_state()               → HedgeState  查询当前状态
      load_state()              → HedgeState  启动时从磁盘恢复状态
    """

    def __init__(self):
        self._state = HedgeState()
        self.load_state()
        self._stop_event = threading.Event()
        self._worker_thread = threading.Thread(target=self._bg_unlock_worker, daemon=True, name="HedgeUnlockWorker")
        self._worker_thread.start()
        # M15 K线数据缓存：避免频繁重复拉取，15 分钟内复用
        self._m15_bars_cache = None
        self._m15_bars_cache_time = 0.0
        self._m15_bars_cache_symbol = ""

    # ------------------------------------------------------------------ #
    #  公开业务方法
    # ------------------------------------------------------------------ #

    def lock(self, symbol: str) -> dict:
        """
        一键锁仓：计算多空净敞口，开等量反向对冲单将风险锁定为零。

        Returns:
            {"status": "success"|"error"|"already_balanced", "message": str, "state": HedgeState}
        """
        if not mt5_client.ensure_connected():
            return {"status": "error", "message": "MT5 terminal disconnected"}

        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return {"status": "error", "message": "当前无持仓，无需锁仓"}

        buy_vol = round(sum(p.volume for p in positions if p.type == mt5.ORDER_TYPE_BUY), 2)
        sell_vol = round(sum(p.volume for p in positions if p.type == mt5.ORDER_TYPE_SELL), 2)
        net = round(buy_vol - sell_vol, 2)

        logger.info(f"锁仓分析 | 品种={symbol} | 多={buy_vol}手 空={sell_vol}手 净敞口={net:+.2f}手")

        if abs(net) < 0.01:
            return {"status": "already_balanced", "message": "多空已平衡，无需对冲锁仓"}

        hedge_dir = "SELL" if net > 0 else "BUY"
        hedge_vol = abs(net)

        logger.warning(f"执行锁仓 | 方向={hedge_dir} 手数={hedge_vol:.2f} 品种={symbol}")
        result = order_executor.place_order(
            symbol, hedge_dir, volume=hedge_vol,
            magic=19999, comment="hedge_lock",
        )

        if result.get("status") == "success":
            ticket = result.get("ticket")
            self._state = HedgeState(
                is_locked=True,
                symbol=symbol,
                hedge_ticket=ticket,
                hedge_direction=hedge_dir,
                hedge_volume=hedge_vol,
                net_exposure_at_lock=net,
                lock_time=datetime.now().isoformat(timespec="seconds"),
                active_unlock_strategy=None,
            )
            self._save_state()
            logger.warning(f"锁仓成功 | ticket={ticket} 方向={hedge_dir} {hedge_vol:.2f}手")
            return {
                "status": "success",
                "message": f"锁仓成功！反向 {hedge_dir} {hedge_vol:.2f}手，ticket=#{ticket}",
                "state": self._state,
            }
        else:
            msg = result.get("message", "未知错误")
            logger.error(f"锁仓失败 | {msg}")
            return {"status": "error", "message": f"锁仓失败：{msg}"}

    def get_market_recommendation(
        self,
        symbol: str,
        prefetched_positions=None,
        prefetched_account=None,
    ) -> dict:
        """
        分析就绪度并给出解仓策略建议。
        可传入已拉取的持仓列表和账户数据，避免重复调用 MT5 API。
        M15 K线有内置缓存，15 分钟内不重新拉取。
        """
        if not mt5_client.ensure_connected():
            return {"status": "error", "message": "MT5 terminal disconnected"}

        # 1. 获取最新 tick 报价（tick 极轻量，始终拉取以保证实时性）
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return {"status": "error", "message": f"无法获取报价 {symbol}"}
        bid = tick.bid
        ask = tick.ask

        # 2. M15 K线数据——优先使用缓存，15 分钟才重新拉取
        now_ts = time.time()
        if (
            self._m15_bars_cache is not None
            and self._m15_bars_cache_symbol == symbol
            and (now_ts - self._m15_bars_cache_time) < 900  # 15 分钟 = 900 秒
        ):
            rates = self._m15_bars_cache
        else:
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 100)
            if rates is not None and len(rates) >= 30:
                self._m15_bars_cache = rates
                self._m15_bars_cache_time = now_ts
                self._m15_bars_cache_symbol = symbol
        if rates is None or len(rates) < 30:
            return {"status": "error", "message": "无法获取M15历史K线数据"}

        # 计算 ATR(20)
        tr_sum = 0.0
        for i in range(len(rates) - 20, len(rates)):
            h = rates[i]['high']
            l = rates[i]['low']
            prev_c = rates[i-1]['close']
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            tr_sum += tr
        atr_20 = tr_sum / 20.0

        # 计算布林带 Bollinger Bands (20, 2)
        closes = [r['close'] for r in rates[-20:]]
        sma_20 = sum(closes) / 20.0
        variance = sum((c - sma_20) ** 2 for c in closes) / 20.0
        std_dev = variance ** 0.5
        upper_bb = sma_20 + 2.0 * std_dev
        lower_bb = sma_20 - 2.0 * std_dev

        # 价格在布林带的位置
        price_position = (bid - lower_bb) / (upper_bb - lower_bb) if (upper_bb - lower_bb) > 0 else 0.5
        bb_width = upper_bb - lower_bb
        recent_slope = rates[-1]['close'] - rates[-5]['close']

        # 3. 核心风控评估：统一将持仓转换为 dict 结构处理
        if prefetched_positions is not None:
            raw_positions = prefetched_positions
        else:
            raw_positions = mt5.positions_get(symbol=symbol)

        positions = []
        if raw_positions:
            for p in raw_positions:
                if hasattr(p, 'ticket'):  # MT5 原始对象
                    positions.append({
                        "volume": p.volume,
                        "type": "BUY" if p.type == 0 else "SELL",
                        "price_open": p.price_open,
                        "magic": p.magic,
                        "comment": p.comment,
                        "profit": getattr(p, "profit", 0.0),
                        "swap": getattr(p, "swap", 0.0),
                        "commission": getattr(p, "commission", 0.0),
                    })
                else:  # 缓存的字典
                    positions.append(p)

        buy_vol = 0.0
        sell_vol = 0.0
        lock_dist = 0.0

        if positions:
            buy_vol = round(sum(p["volume"] for p in positions if p["type"] == "BUY"), 2)
            sell_vol = round(sum(p["volume"] for p in positions if p["type"] == "SELL"), 2)

            buy_sum = sum(p["price_open"] * p["volume"] for p in positions if p["type"] == "BUY")
            sell_sum = sum(p["price_open"] * p["volume"] for p in positions if p["type"] == "SELL")

            buy_avg = buy_sum / buy_vol if buy_vol > 0 else 0.0
            sell_avg = sell_sum / sell_vol if sell_vol > 0 else 0.0

            # 多空对冲持仓均价间距（锁仓跨度）
            lock_dist = abs(buy_avg - sell_avg) if (buy_vol > 0 and sell_vol > 0) else 0.0

        # 统一将账户数据转换为 dict 结构处理
        if prefetched_account is not None:
            ac_dict = prefetched_account
        else:
            ac = mt5.account_info()
            if ac:
                ac_dict = {
                    "margin_level": ac.margin_level if ac.margin > 0 else 9999.0,
                    "margin": ac.margin,
                    "equity": ac.equity,
                    "balance": ac.balance,
                }
            else:
                ac_dict = {
                    "margin_level": 9999.0,
                    "margin": 0.0,
                    "equity": 0.0,
                    "balance": 0.0,
                }

        margin_level = ac_dict.get("margin_level", 9999.0)
        margin = ac_dict.get("margin", 0.0)
        if margin <= 0:
            margin_level = 9999.0
        equity = ac_dict.get("equity", 0.0)
        balance = ac_dict.get("balance", 0.0)

        # 计算短线波动率 (近5根 M15 柱子) 以计算波动降温因子 VCF
        vcf = 1.0
        if rates is not None and len(rates) >= 25:
            tr_sum_5 = 0.0
            for i in range(len(rates) - 5, len(rates)):
                h = rates[i]['high']
                l = rates[i]['low']
                prev_c = rates[i-1]['close']
                tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
                tr_sum_5 += tr
            atr_5 = tr_sum_5 / 5.0
            vcf = atr_5 / atr_20 if atr_20 > 0 else 1.0

        # 计算实时点差
        current_spread = ask - bid

        # 评估 5 分钟锁仓冷静期 (冷静期内强制冷静观察)
        is_cooldown_passed = True
        cooldown_remaining_secs = 0
        if self._state.is_locked and self._state.lock_time:
            try:
                lock_dt = datetime.fromisoformat(self._state.lock_time)
                elapsed = (datetime.now() - lock_dt).total_seconds()
                if elapsed < 300:  # 5分钟 = 300秒
                    is_cooldown_passed = False
                    cooldown_remaining_secs = int(300 - elapsed)
            except Exception:
                pass

        # 智能研判解仓就绪度 (URI)：基于持仓实际盈亏 (P&L) 的核心风控评判
        readiness_status = "READY"
        readiness_reasons = []
        readiness_score = 100

        # 计算当前持仓的总浮动盈亏（包含利息和手续费）
        total_pnl = sum(p.get("profit", 0.0) + p.get("swap", 0.0) + p.get("commission", 0.0) for p in positions) if positions else 0.0

        if not positions:
            readiness_score = 100
            readiness_status = "READY"
            readiness_reasons.append("🟢 当前无持仓，系统安全态。")
        else:
            # 依据 P&L 确定基础就绪分
            if total_pnl >= 0.0:
                base_score = 100
                readiness_reasons.append(f"🟢 当前对冲持仓实现整体净盈利（实时盈亏: +${total_pnl:.2f}），已达最佳解仓黄金窗口！")
            elif total_pnl >= -10.0:
                base_score = 90
                readiness_reasons.append(f"🟢 当前对冲持仓接近盈亏平衡（实时盈亏: ${total_pnl:.2f}），具备良好解仓条件。")
            elif total_pnl >= -50.0:
                base_score = 75
                readiness_reasons.append(f"🕒 对冲持仓目前处于轻度浮亏中（实时盈亏: ${total_pnl:.2f}），建议观察或用安全策略解仓。")
            else:
                # 较重浮亏，分值随亏损加深而衰减，最低 30 分
                loss_factor = min(1.0, abs(total_pnl) / 500.0)
                base_score = int(70 - (40 * loss_factor))
                readiness_reasons.append(f"❌ 对冲持仓目前浮亏较重（实时盈亏: ${total_pnl:.2f}），直接平仓损失较大，建议用策略蚕食。")

            readiness_score = base_score

        # 极端风险风控红线（保证金极低）
        if margin_level < 200.0:
            readiness_score = min(readiness_score, 30)
            readiness_reasons.append(f"🚨 账户保证金比例告急（当前仅 {margin_level:.1f}%），已处于随时强平爆仓线。")

        # 锁仓冷静期限制（次要扣分点）
        if not is_cooldown_passed:
            cooldown_deduct = 10 if total_pnl < 0 else 5
            readiness_score -= cooldown_deduct
            readiness_reasons.append(f"🔒 处于锁仓冷静期（剩余冷静时间: {cooldown_remaining_secs} 秒），注意短期波动。")

        # 波动洪峰因素（次要扣分点，仅在波动率极高时轻微影响）
        if vcf > 1.5:
            readiness_score -= 10
            readiness_reasons.append(f"⚡ 黄金短线波动异常偏高（当前是常态的 {vcf:.1f} 倍），建仓/平仓注意滑点。")

        # 点差因素（次要扣分点）
        if current_spread > 5.0:
            readiness_score -= 5
            readiness_reasons.append(f"🚨 经纪商实时点差异常偏宽（当前 {current_spread:.2f} 美元），交易滑点成本略微上升。")

        # 边界与最终状态判定
        if readiness_score < 0:
            readiness_score = 0
        if readiness_score > 100:
            readiness_score = 100

        if margin_level < 200.0:
            readiness_status = "CRITICAL_RISK"
        elif readiness_score >= 85:
            readiness_status = "READY"
        elif readiness_score >= 50:
            readiness_status = "OBSERVING"
        else:
            readiness_status = "CRITICAL_RISK"
        
        # 4. 融合决策模型 (技术面 + 资金风控面)
        trend_state = "UNKNOWN"
        recommendation_key = ""
        recommendation = ""
        reason = ""

        # A. 极端风控红线：若保证金比例低于 200%
        if margin_level < 200.0:
            trend_state = "MARGIN_CRITICAL"
            recommendation_key = "profit_offset"
            recommendation = "S2 盈利冲抵法"
            reason = f"🚨【资金红线警报】当前账户保证金比例仅 {margin_level:.1f}%，已处于爆仓高危区！此状态下绝对禁止启用 S4 网格加仓。强烈建议立即启用 S2 盈利冲抵（或 S1 直接两两冲抵），利用其他小仓位稳定盈利逐步分批蚕食浮亏，绝不增加任何新的持仓风险！"

        # B. 大跨度宽幅锁仓：锁仓价格间距过宽 (大于 4.0 * ATR，黄金约 22 美元以上)
        elif lock_dist > 4.0 * atr_20:
            # 宽幅锁仓情况下，若行情正处于强势突破或高动能状态，强烈推荐 S3 突破跟踪
            if price_position > 1.05 or price_position < -0.05 or abs(recent_slope) > 3.0 * atr_20:
                trend_state = "WIDE_LOCK_BREAKOUT"
                recommendation_key = "breakout_trail"
                recommendation = "S3 区间突破跟踪法"
                reason = f"📊【宽幅锁仓突破】您的多空持仓均价间距达 {lock_dist:.2f} 美元，跨度极宽。当前黄金刚好爆发出单边突破动能。此时最聪明的选择是 S3，顺势平仓亏损侧，保留盈利侧跟随移动止盈，以趋势的巨大单边暴利去彻底覆盖并剿灭这笔宽幅浮亏！"
            else:
                trend_state = "WIDE_LOCK_OSCILLATING"
                recommendation_key = "profit_offset"
                recommendation = "S2 盈利冲抵法"
                reason = f"📊【宽幅锁仓震荡】多空持仓间距达 {lock_dist:.2f} 美元，跨度宽，但当前黄金正处于温和盘整阶段。在此行情下，网格加仓空间跨度过大，安全系数低。建议开启 S2 盈利冲抵作为安全气垫，利用外部刷单利润稳步分批平仓，静待市场突破。"

        # C. 窄幅/中等锁仓且保证金充沛：如果布林带极度收紧或市场标准震荡，可以安全启用 S4
        elif margin_level > 500.0 and bb_width < 1.8 * atr_20:
            # 保证金安全系数极高 (>500%)，锁仓跨度合理，市场无强单边暴动
            trend_state = "SAFE_DCA_ZONE"
            recommendation_key = "dca_merge"
            recommendation = "S4 DCA 均价合并法"
            reason = f"🎯【AI 黄金方案】当前多空跨度适中（{lock_dist:.2f} 美元），账户保证金比例达 {margin_level:.1f}%，抗风险能力好。且布林带通道处于收紧盘整区，未见单边动能。此时正是启用 S4 的绝佳时机！可以通过顺势 1.5 倍马丁网格平摊均价，在价格震荡回踩的瞬间触发整体保本平仓，解仓效率最高！"

        # D. 标准宽幅震荡行情 (默认兜底)
        else:
            if price_position > 1.05 or price_position < -0.05 or abs(recent_slope) > 3.0 * atr_20:
                trend_state = "STRONG_TREND_BREAKOUT"
                recommendation_key = "breakout_trail"
                recommendation = "S3 区间突破跟踪法"
                reason = f"⚡【强单边突破】黄金当前价格已冲破布林带边缘（当前位置 {price_position*100:.1f}%），短期动能斜率达 {recent_slope:+.2f}，行情正在单边暴动不回头。强烈建议开启 S3，平亏损，留盈利，让盈利侧去狂奔并吃掉浮亏。"
            else:
                trend_state = "STANDARD_OSCILLATING"
                recommendation_key = "profit_offset"
                recommendation = "S2 盈利冲抵法"
                reason = f"🔄【温和区间震荡】当前多空跨度为 {lock_dist:.2f} 美元，黄金处于标准的布林带箱体震荡区内（相对位置 {price_position*100:.1f}%），暂无强单边苗头。最稳健的做法是启动 S2 盈利冲抵，借助其他平稳刷单产生的收益，无风险地分批消融浮亏。"

        return {
            "status": "success",
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "atr": atr_20,
            "sma_20": sma_20,
            "upper_bb": upper_bb,
            "lower_bb": lower_bb,
            "price_position": price_position,
            "bb_width": bb_width,
            "recent_slope": recent_slope,
            "trend_state": trend_state,
            "recommendation_key": recommendation_key,
            "recommendation": recommendation,
            "reason": reason,
            "readiness": {
                "status": readiness_status,
                "score": readiness_score,
                "is_ready": (readiness_status == "READY"),
                "reasons": readiness_reasons,
                "vcf": vcf,
                "spread": current_spread
            },
            "account_info": {
                "balance": balance,
                "equity": equity,
                "margin_level": margin_level,
                "lock_dist": lock_dist,
                "buy_vol": buy_vol,
                "sell_vol": sell_vol
            }
        }

    def unlock(self, symbol: str, strategy: str) -> dict:
        """
        智能解仓：根据选定策略执行 MQL5 级别的解仓算法。

        strategy 可选值：
          "closeby"       — MT5 TRADE_ACTION_CLOSE_BY 双向冲抵（零点差，真实执行）
          "profit_offset" — 盈利冲抵法（接口预留，待策略模块实现）
          "breakout_trail"— 区间突破跟踪（接口预留，待策略模块实现）
          "dca_merge"     — DCA 均价合并（接口预留，待策略模块实现）

        Returns:
            {"status": "success"|"error"|"activated", "message": str}
        """
        logger.warning(f"执行解仓 | 策略={strategy} 品种={symbol}")

        if not mt5_client.ensure_connected():
            return {"status": "error", "message": "MT5 terminal disconnected"}

        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            self._state = HedgeState()
            self._save_state()
            return {"status": "error", "message": "当前无持仓，无需解仓"}

        buys = [p for p in positions if p.type == mt5.ORDER_TYPE_BUY]
        sells = [p for p in positions if p.type == mt5.ORDER_TYPE_SELL]
        if not buys or not sells:
            self._state.is_locked = False
            self._state.hedge_ticket = None
            self._state.active_unlock_strategy = None
            self._save_state()
            return {"status": "error", "message": "当前不是多空对冲状态，无法执行智能解仓"}

        if strategy == "closeby":
            result = order_executor.close_by_opposite(symbol)
            count = result.get("count", 0)
            if result.get("status") == "success":
                if count > 0:
                    # 冲抵完成后重新检查是否还有剩余持仓
                    remaining = mt5.positions_get(symbol=symbol)
                    if not remaining:
                        # 全部解除
                        self._state = HedgeState()
                        self._save_state()
                    else:
                        # 更新状态：仍有净敞口但对冲单已减少
                        self._update_lock_status_from_positions(symbol, remaining)
                    logger.warning(f"CloseBy 冲抵完成 | 已处理 {count} 对订单")
                    return {
                        "status": "success",
                        "message": f"CloseBy 冲抵成功！已处理 {count} 对订单，零点差成本",
                    }
                else:
                    return {"status": "error", "message": result.get("message", "无可冲抵的对手方持仓")}
            else:
                return {"status": "error", "message": result.get("message", "CloseBy 执行失败")}

        elif strategy == "profit_offset":
            tick = mt5.symbol_info_tick(symbol)
            current_price = tick.bid if tick else 0.0
            self._state.active_unlock_strategy = "profit_offset"
            self._state.lock_price = current_price
            self._state.offset_used_profit = 0.0
            self._state.is_locked = True
            self._save_state()
            return {
                "status": "activated",
                "message": f"盈利冲抵策略已激活！基准价={current_price}。系统将每赚 $5 自动部分平仓浮亏最重的对冲单。",
            }

        elif strategy == "breakout_trail":
            tick = mt5.symbol_info_tick(symbol)
            current_price = tick.bid if tick else 0.0
            self._state.active_unlock_strategy = "breakout_trail"
            self._state.lock_price = current_price
            self._state.breakout_direction = None
            self._state.highest_price_since_breakout = 0.0
            self._state.lowest_price_since_breakout = 0.0
            self._state.is_locked = True
            self._save_state()
            return {
                "status": "activated",
                "message": f"区间突破跟踪策略已激活！基准价={current_price}。突破 ATR 上下轨后平仓亏损侧并对盈利侧启动 Trailing Stop。",
            }

        elif strategy == "dca_merge":
            tick = mt5.symbol_info_tick(symbol)
            current_price = tick.bid if tick else 0.0
            self._state.active_unlock_strategy = "dca_merge"
            self._state.lock_price = current_price
            self._state.dca_level = 0
            self._state.last_dca_price = 0.0
            self._state.is_locked = True
            self._save_state()
            return {
                "status": "activated",
                "message": f"DCA 均价合并策略已激活！基准价={current_price}。系统开始按 1.5 倍马丁布置补仓网格，盈亏保本后一键全平。",
            }

        else:
            return {"status": "error", "message": f"未知解仓策略: {strategy}"}

    def close_all(self, symbol: str) -> dict:
        """
        一键全平：关闭指定品种所有持仓（无论 Magic），清除锁仓状态。

        Returns:
            {"status": "success"|"error", "message": str, "count": int}
        """
        logger.warning(f"执行一键全平 | 品种={symbol}")
        result = order_executor.close_all_for_symbol(symbol)
        count = result.get("count", 0)

        if result.get("status") == "success":
            # 清除锁仓状态
            self._state = HedgeState()
            self._save_state()
            logger.warning(f"一键全平完成 | 成功平仓 {count} 笔")
            return {
                "status": "success",
                "message": f"极速全平完成！成功处理 {count} 笔订单",
                "count": count,
            }
        else:
            msg = result.get("message", "未知错误")
            logger.error(f"一键全平失败 | {msg}")
            return {"status": "error", "message": f"全平失败：{msg}", "count": 0}

    def reset_lock_state(self):
        """强制重置/清除锁仓和解仓状态（不执行任何平仓/下单）。"""
        self._state = HedgeState()
        self._save_state()
        logger.warning("手动强制重置锁仓与解仓状态，清空所有记录。")

    def get_state(self) -> HedgeState:
        """返回当前对冲状态快照（只读）。"""
        return self._state

    def reconcile_state(self, symbol: str) -> HedgeState:
        """Refresh persisted lock state against live MT5 positions."""
        if not mt5_client.ensure_connected():
            return self._state

        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            if self._state.is_locked:
                self._state = HedgeState()
                self._save_state()
            return self._state

        buys = [p for p in positions if p.type == mt5.ORDER_TYPE_BUY]
        sells = [p for p in positions if p.type == mt5.ORDER_TYPE_SELL]
        if not buys or not sells:
            if self._state.is_locked:
                self._state.is_locked = False
                self._state.hedge_ticket = None
                self._state.active_unlock_strategy = None
                self._save_state()
            return self._state

        if self._state.is_locked and self._state.hedge_ticket:
            live_tickets = {p.ticket for p in positions}
            if self._state.hedge_ticket not in live_tickets:
                buy_vol = round(sum(p.volume for p in buys), 2)
                sell_vol = round(sum(p.volume for p in sells), 2)
                self._state.hedge_ticket = None
                self._state.hedge_volume = round(min(buy_vol, sell_vol), 2)
                self._save_state()

        return self._state

    def load_state(self) -> HedgeState:
        """
        从磁盘读取上次保存的锁仓状态。
        程序启动时调用，确保 UI 能正确渲染上次的锁仓记录。
        """
        if not os.path.exists(_STATE_FILE):
            self._state = HedgeState()
            return self._state

        try:
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._state = HedgeState.from_dict(data)
            if self._state.is_locked:
                logger.info(
                    f"恢复锁仓状态 | 品种={self._state.symbol} "
                    f"ticket=#{self._state.hedge_ticket} "
                    f"锁仓时间={self._state.lock_time}"
                )
        except Exception as exc:
            logger.error(f"读取锁仓状态文件失败，将重置: {exc}")
            self._state = HedgeState()

        return self._state

    # ------------------------------------------------------------------ #
    #  内部辅助方法
    # ------------------------------------------------------------------ #

    def _save_state(self):
        """将当前状态序列化写入 JSON 文件。"""
        try:
            os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
            with open(_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._state.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.error(f"保存锁仓状态失败: {exc}")

    def _update_lock_status_from_positions(self, symbol: str, positions):
        """CloseBy 部分解仓后，根据剩余持仓更新状态。"""
        buys = [p for p in positions if p.type == mt5.ORDER_TYPE_BUY]
        sells = [p for p in positions if p.type == mt5.ORDER_TYPE_SELL]
        still_hedged = bool(buys and sells)

        if not still_hedged:
            self._state.is_locked = False
            self._state.hedge_ticket = None
        else:
            # 仍有对冲，但量可能已经减少，更新一下记录
            pass
        self._save_state()

    def _bg_unlock_worker(self):
        logger.info("对冲解仓后台监控线程已就绪")
        while not self._stop_event.is_set():
            try:
                time.sleep(2.0) # 每2秒检查一次
                
                # 如果没有开启对冲锁仓，或者没有激活解仓策略，则跳过
                if not self._state.is_locked or not self._state.active_unlock_strategy:
                    continue
                
                symbol = self._state.symbol
                strategy = self._state.active_unlock_strategy
                
                if not mt5_client.ensure_connected():
                    continue
                
                # 定期刷新和校验持仓状态，确保锁仓记录与实际持仓匹配
                self.reconcile_state(symbol)
                if not self._state.is_locked or not self._state.active_unlock_strategy:
                    continue
                
                # 执行具体的策略逻辑
                if strategy == "profit_offset":
                    self._run_profit_offset_logic(symbol)
                elif strategy == "breakout_trail":
                    self._run_breakout_trail_logic(symbol)
                elif strategy == "dca_merge":
                    self._run_dca_merge_logic(symbol)
                    
            except Exception as e:
                logger.error(f"对冲解仓监控循环异常: {e}")

    def _get_atr(self, symbol: str) -> float:
        try:
            bars = mt5_client.get_history_bars(symbol, mt5.TIMEFRAME_M15, 21)
            if len(bars) < 21:
                return 1.50
            tr_sum = 0.0
            for i in range(1, len(bars)):
                h = bars[i]['high']
                l = bars[i]['low']
                prev_c = bars[i-1]['close']
                tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
                tr_sum += tr
            return round(tr_sum / 20.0, 2)
        except Exception as e:
            logger.error(f"计算 ATR 失败，使用默认值 1.5: {e}")
            return 1.50

    def _run_profit_offset_logic(self, symbol: str):
        # 1. 解析锁仓时间，如果有错误则以昨天为基准
        try:
            lock_dt = datetime.fromisoformat(self._state.lock_time)
        except Exception:
            lock_dt = datetime.now() - timedelta(days=1)

        # 2. 获取锁仓开始至今的所有 Deals 历史
        deals_data = mt5_client.get_trade_history(days=30)
        if not deals_data or "deals" not in deals_data:
            return

        # 3. 统计非对冲单（magic != 19999 且不含对冲标记）的净盈利总和
        lock_timestamp = int(lock_dt.timestamp())
        accumulated_profit = 0.0
        for deal in deals_data["deals"]:
            if deal.get("time_raw", 0) >= lock_timestamp:
                comment = deal.get("comment", "")
                if "hedge_lock" in comment or "hedge_dca" in comment:
                    continue
                prof = deal.get("profit", 0.0)
                if prof > 0:
                    accumulated_profit += prof

        # 4. 计算可用利润额度
        available_profit = accumulated_profit - self._state.offset_used_profit
        if available_profit < 5.0:
            return

        logger.warning(f"盈利冲抵触发 | 累计可对冲利润={accumulated_profit:.2f} 已用={self._state.offset_used_profit:.2f} 可用={available_profit:.2f}")

        # 5. 检索当前浮亏最严重的单子（不限 magic，只要是 symbol 下的）
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            # 没有持仓了，解仓结束
            self._state = HedgeState()
            self._save_state()
            return

        worst_pos = min(positions, key=lambda p: p.profit)
        if worst_pos.profit >= 0:
            logger.info("当前所有持仓均已转为盈利，盈利冲抵结束")
            return

        # 执行平仓：平掉 0.01 手
        vol_to_close = 0.01
        if worst_pos.volume <= 0.01:
            result = order_executor.close_position(worst_pos.ticket)
        else:
            result = order_executor.partial_close_position(worst_pos.ticket, vol_to_close)

        if result.get("status") == "success":
            self._state.offset_used_profit += 5.0
            self._save_state()
            logger.warning(f"盈利冲抵执行成功！使用 $5 利润部分平仓单 #{worst_pos.ticket} ({worst_pos.volume:.2f}手 -> 减少0.01手)")
            # 平仓后，重新校验一次状态，看是否还有多空对冲
            time.sleep(0.5)
            self.reconcile_state(symbol)

    def _run_breakout_trail_logic(self, symbol: str):
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return

        current_price = tick.bid
        atr = self._get_atr(symbol)
        
        # 1. 如果尚未确定突破方向，检测是否突破
        if self._state.breakout_direction is None:
            if self._state.lock_price == 0.0:
                self._state.lock_price = current_price
                self._save_state()
                return

            upper_band = self._state.lock_price + 2.0 * atr
            lower_band = self._state.lock_price - 2.0 * atr

            if current_price > upper_band:
                # 向上突破：平掉所有空头，多头保留加 Trailing Stop
                logger.warning(f"S3 向上突破激活！当前价={current_price} 突破上轨={upper_band:.2f}，正在清空所有空头仓位...")
                positions = mt5.positions_get(symbol=symbol)
                sells = [p for p in positions if p.type == mt5.ORDER_TYPE_SELL]
                for p in sells:
                    order_executor.close_position(p.ticket)
                
                self._state.breakout_direction = "UP"
                self._state.highest_price_since_breakout = current_price
                self._save_state()

            elif current_price < lower_band:
                # 向下突破：平掉所有多头，空头保留加 Trailing Stop
                logger.warning(f"S3 向下突破激活！当前价={current_price} 突破下轨={lower_band:.2f}，正在清空所有多头仓位...")
                positions = mt5.positions_get(symbol=symbol)
                buys = [p for p in positions if p.type == mt5.ORDER_TYPE_BUY]
                for p in buys:
                    order_executor.close_position(p.ticket)
                
                self._state.breakout_direction = "DOWN"
                self._state.lowest_price_since_breakout = current_price
                self._save_state()

        # 2. 如果已经确定突破方向，执行 Trailing Stop
        elif self._state.breakout_direction == "UP":
            self._state.highest_price_since_breakout = max(self._state.highest_price_since_breakout, current_price)
            self._save_state()

            ts_price = self._state.highest_price_since_breakout - 1.5 * atr
            if current_price < ts_price:
                logger.warning(f"S3 多头移动止盈触发！当前价={current_price} 跌破止损位={ts_price:.2f}，全平多头解仓。")
                positions = mt5.positions_get(symbol=symbol)
                buys = [p for p in positions if p.type == mt5.ORDER_TYPE_BUY]
                for p in buys:
                    order_executor.close_position(p.ticket)
                
                # 解仓完成，重置状态
                self._state = HedgeState()
                self._save_state()

        elif self._state.breakout_direction == "DOWN":
            self._state.lowest_price_since_breakout = min(self._state.lowest_price_since_breakout, current_price)
            self._save_state()

            ts_price = self._state.lowest_price_since_breakout + 1.5 * atr
            if current_price > ts_price:
                logger.warning(f"S3 空头移动止盈触发！当前价={current_price} 突破止损位={ts_price:.2f}，全平空头解仓。")
                positions = mt5.positions_get(symbol=symbol)
                sells = [p for p in positions if p.type == mt5.ORDER_TYPE_SELL]
                for p in sells:
                    order_executor.close_position(p.ticket)
                
                # 解仓完成，重置状态
                self._state = HedgeState()
                self._save_state()

    def _run_dca_merge_logic(self, symbol: str):
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            self._state = HedgeState()
            self._save_state()
            return

        # 1. 每一轮询，检查整个 symbol 组合的净盈亏之和（保本微利全平）
        total_profit = sum(p.profit + getattr(p, "commission", 0.0) + getattr(p, "swap", 0.0) for p in positions)
        if total_profit >= 5.0:
            logger.warning(f"S4 DCA均价合并成功！当前大篮子总盈亏达 {total_profit:.2f} 元，触发极速全平解仓！")
            self.close_all(symbol)
            return

        # 2. 如果尚未达到保本价，且当前价格触发网格点，顺势加仓马丁
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return
        
        current_price = tick.bid
        atr = self._get_atr(symbol)
        spacing = 1.5 * atr
        
        if self._state.last_dca_price == 0.0:
            self._state.last_dca_price = self._state.lock_price if self._state.lock_price > 0.0 else current_price
            self._save_state()
            return

        if self._state.dca_level >= 4:
            return

        # 顺势网格加仓逻辑
        diff = current_price - self._state.last_dca_price
        triggered = False
        dca_dir = ""
        
        if diff >= spacing:
            triggered = True
            dca_dir = "BUY"
        elif diff <= -spacing:
            triggered = True
            dca_dir = "SELL"
            
        if triggered:
            vol = round(self._state.hedge_volume * (1.5 ** (self._state.dca_level + 1)), 2)
            if vol < 0.01:
                vol = 0.01
                
            logger.warning(f"S4 DCA 网格触发加仓！方向={dca_dir} 手数={vol:.2f} 当前层级={self._state.dca_level + 1}")
            
            res = order_executor.place_order(
                symbol, dca_dir, volume=vol,
                magic=19998, comment="hedge_dca"
            )
            
            if res.get("status") == "success":
                self._state.dca_level += 1
                self._state.last_dca_price = current_price
                self._save_state()
                logger.warning(f"S4 DCA 加仓成功 | ticket={res.get('ticket')}，下一加仓基准价={current_price}")


# 全局单例，供 UI 和其他模块直接 import 使用
hedge_manager = HedgeManager()
