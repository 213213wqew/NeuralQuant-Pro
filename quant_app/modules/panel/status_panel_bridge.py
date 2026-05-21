import os
import time

import MetaTrader5 as mt5
import pandas as pd

from quant_app.core.market_data_center import market_data_center
from quant_app.core.logger import get_logger

logger = get_logger("MT5StatusPanelBridge")

_ai_cache = {}
_failed_imports = set()


class MT5StatusPanelBridge:
    """Export strategy status for the MT5 panel."""

    def __init__(self, symbol: str, magic: int, strategy_name: str):
        self.symbol = symbol
        self.magic = int(magic)
        self.strategy_name = strategy_name
        self.export_path = None
        self._logged_export_path = False

    def export(self, payload: dict) -> None:
        self.export_path = self._build_export_path()
        if not self.export_path:
            return

        status_payload = dict(payload)
        status_payload["updated_at"] = int(time.time())

        try:
            status_payload["account_scope"] = self._account_scope()
            status_payload.update(self._ai_status_fields(status_payload))
        except Exception as exc:
            logger.debug("status field generation failed: %s", exc)

        self._write_to_file(self.export_path, status_payload)

        if self.strategy_name == "GridMartingaleMA02":
            try:
                ma01_path = self.export_path.replace("GridMartingaleMA02", "GridMartingaleMA01")
                self._write_to_file(ma01_path, status_payload)
            except Exception:
                pass

        if not self._logged_export_path:
            logger.info("panel status export path: %s", self.export_path)
            self._logged_export_path = True

    def _write_to_file(self, path: str, data: dict):
        temp_path = f"{path}.tmp"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(temp_path, "w", encoding="gbk", errors="ignore") as handle:
                handle.writelines([f"{key}={value}\n" for key, value in data.items()])

            if os.path.exists(path):
                os.remove(path)
            os.rename(temp_path, path)
        except Exception as exc:
            logger.debug("panel file write busy: %s", exc)

    def _safe_name(self, value: str) -> str:
        out = ""
        for ch in str(value):
            if ("0" <= ch <= "9") or ("A" <= ch <= "Z") or ("a" <= ch <= "z"):
                out += ch
            else:
                out += "_"
        return out

    def _account_scope(self) -> str:
        try:
            account = mt5.account_info()
            if not account:
                return "0_server"
            return self._safe_name(f"{account.login}_{account.server}")
        except Exception:
            return "0_server"

    def _build_export_path(self):
        common_dir = self._mt5_common_files_dir()
        if not common_dir:
            return None

        account_id = "0"
        try:
            account = mt5.account_info()
            if account:
                account_id = str(account.login)
        except Exception:
            pass

        folder = self.strategy_name or "GridMartingaleMA01"
        safe_symbol = self._safe_name(self.symbol)
        target_dir = os.path.join(common_dir, "NeuralQuant", folder, self._account_scope())
        return os.path.join(target_dir, f"{safe_symbol}_{account_id}.txt")

    def _mt5_common_files_dir(self) -> str | None:
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        return os.path.join(appdata, "MetaQuotes", "Terminal", "Common", "Files")

    def _cn_ai_direction(self, code: str) -> str:
        if code == "BUY":
            return "偏多"
        if code == "SELL":
            return "偏空"
        return "震荡"

    def _cn_ai_regime(self, code: str) -> str:
        mapping = {
            "trending": "趋势中",
            "ranging": "震荡中",
            "transition": "过渡中",
            "initializing": "初始化",
            "error": "异常",
            "unknown": "未知",
        }
        return mapping.get(str(code), str(code))

    def _cn_ai_quality(self, code: str) -> str:
        mapping = {
            "confirmed": "已确认",
            "wait": "未达确认",
            "risk_blocked": "风险拦截",
            "insufficient_data": "数据不足",
            "error": "异常",
            "unknown": "未知",
        }
        return mapping.get(str(code), str(code))

    def _cn_ai_family(self, code: str) -> str:
        mapping = {
            "ensemble_gru_trend": "GRU+趋势共振",
            "qlib_gru": "GRU模型",
            "none": "无",
        }
        return mapping.get(str(code), str(code))

    def _cn_shock(self, code: str) -> str:
        mapping = {
            "none": "无预警",
            "potential": "潜在冲击",
            "high_risk": "高风险冲击",
            "active_move": "异动进行中",
            "upside_shock": "上涨预警",
            "downside_shock": "下跌预警",
            "upside_impulse": "上涨冲击",
            "downside_impulse": "下跌冲击",
        }
        return mapping.get(str(code), str(code))

    def _cn_shock_direction(self, code: str) -> str:
        mapping = {
            "upside": "向上",
            "downside": "向下",
            "uncertain": "不确定",
            "none": "无",
        }
        return mapping.get(str(code), str(code))

    def _cn_downside_state(self, code: str) -> str:
        mapping = {
            "normal": "正常",
            "downside_watch": "下行观察",
            "watch_hold": "观察锁定",
            "block_hold": "拦截锁定",
            "fast_drop": "快速下跌",
            "slow_bleed": "缓慢阴跌",
            "extreme_downtrend": "极端下行",
            "downside_impulse": "极端暴跌",
            "upside_impulse": "极速暴涨",
            "upside_shock": "快速上涨",
            "upside_watch": "上行观察",
            "upside_slow": "温和上涨",
            "unknown": "未知",
        }
        return mapping.get(str(code), str(code))

    def _cn_votes(self, value: str) -> str:
        mapping = {
            "ema_up": "均线上行",
            "ema_down": "均线下行",
            "ema_flat": "均线不明",
            "momentum_up": "动量向上",
            "momentum_down": "动量向下",
            "momentum_weak": "动量弱",
            "adx_weak": "趋势弱",
            "breakout_up": "向上突破",
            "breakout_down": "向下突破",
            "no_breakout": "无突破",
            "gru_buy": "模型看多",
            "gru_sell": "模型看空",
            "gru_neutral": "模型中性",
            "gru_missing": "模型缺失",
        }
        parts = [p.strip() for p in str(value or "").split(",") if p.strip()]
        return "，".join(mapping.get(p, p) for p in parts) if parts else "-"

    def _cn_risk_flags(self, value: str) -> str:
        mapping = {
            "none": "无",
            "atr_too_low": "波动过低",
            "volatility_spike": "波动突增",
            "volatility_squeeze": "波动压缩",
            "range_or_noise": "震荡噪音",
        }
        parts = [p.strip() for p in str(value or "").split(",") if p.strip()]
        return "，".join(mapping.get(p, p) for p in parts) if parts else "无"

    def _cn_trade_advice(self, prediction: dict, shock: dict | None = None) -> str:
        quality = prediction.get("ai_decision_quality", "unknown")
        trade_direction = prediction.get("ai_trade_direction", "NEUTRAL")
        risk_flags = prediction.get("ai_risk_flags", "none")
        shock_level = (shock or {}).get("shock_level", "none")

        if quality == "risk_blocked" or risk_flags not in ("", "-", "none"):
            return "暂停开仓"
        if shock_level in ("high_risk", "active_move"):
            return "等待回稳"
        if quality == "confirmed" and trade_direction == "BUY":
            return "执行多头"
        if quality == "confirmed" and trade_direction == "SELL":
            return "执行空头"
        if quality == "insufficient_data":
            return "数据不足"
        return "观望"

    def _cn_v_model_confirm(self, v_reversal: dict) -> str:
        prediction = v_reversal.get("v_prediction", "NEUTRAL")
        model_type = v_reversal.get("v_model_type", "")
        if model_type == "lightgbm_v_reversal" and prediction == "BUY":
            return "确认偏多"
        if model_type == "lightgbm_v_reversal" and prediction == "SELL":
            return "确认偏空"
        return "无模型确认"

    def _cn_v_reliability(self, v_reversal: dict) -> str:
        prediction = v_reversal.get("v_prediction", "NEUTRAL")
        model_type = v_reversal.get("v_model_type", "")
        confidence = float(v_reversal.get("v_confidence", 0.0) or 0.0)
        if model_type != "lightgbm_v_reversal" or prediction == "NEUTRAL":
            return "低"
        if confidence >= 0.70:
            return "高"
        if confidence >= 0.60:
            return "中"
        return "低"

    def _cn_reason(self, prediction: dict) -> str:
        trend_direction = prediction.get("ai_direction", "NEUTRAL")
        model_direction = prediction.get("ai_model_direction", "NEUTRAL")
        quality = prediction.get("ai_decision_quality", "unknown")
        prob = float(prediction.get("ai_probability", 0.5) or 0.5)

        if trend_direction != "NEUTRAL" and model_direction == "NEUTRAL":
            return f"趋势{self._cn_ai_direction(trend_direction)}，但模型概率{prob:.4f}"
        if trend_direction != "NEUTRAL" and trend_direction != model_direction:
            return f"趋势{self._cn_ai_direction(trend_direction)}，但模型判断相反"
        if quality == "confirmed":
            return f"趋势与模型一致，当前方向{self._cn_ai_direction(trend_direction)}"
        return "趋势和模型暂未形成一致结论"

    def _safe_ai_prediction(self, df):
        if "ai_engine" in _failed_imports:
            return {
                "ai_direction": "NEUTRAL",
                "ai_model_direction": "NEUTRAL",
                "ai_trade_direction": "NEUTRAL",
                "ai_confidence": 0.0,
                "ai_probability": 0.5,
                "ai_regime": "unknown",
                "ai_trend_family": "none",
                "ai_decision_quality": "error",
                "ai_score": 0.0,
                "ai_votes": "gru_missing",
                "ai_risk_flags": "none",
            }
        try:
            from quant_app.modules.ai.inference import ai_engine

            return ai_engine.predict(df)
        except Exception as exc:
            _failed_imports.add("ai_engine")
            logger.warning("AI inference branch unavailable: %s", exc)
            return {
                "ai_direction": "NEUTRAL",
                "ai_model_direction": "NEUTRAL",
                "ai_trade_direction": "NEUTRAL",
                "ai_confidence": 0.0,
                "ai_probability": 0.5,
                "ai_regime": "unknown",
                "ai_trend_family": "none",
                "ai_decision_quality": "error",
                "ai_score": 0.0,
                "ai_votes": "gru_missing",
                "ai_risk_flags": "none",
            }

    def _safe_ml_short_prediction(self, df):
        if "short_term_ml_predictor" in _failed_imports:
            return {
                "ml_short_direction": "NEUTRAL",
                "ml_short_direction_cn": "短线无可靠方向",
                "ml_short_confidence": 0.0,
                "ml_short_horizon": 0,
                "ml_short_reason": "短线模型不可用",
                "ml_short_model_type_cn": "短线模型不可用",
            }
        try:
            from quant_app.modules.ai.short_term_model import short_term_ml_predictor

            return short_term_ml_predictor.predict(df)
        except Exception as exc:
            _failed_imports.add("short_term_ml_predictor")
            logger.warning("Short-term ML branch unavailable: %s", exc)
            return {
                "ml_short_direction": "NEUTRAL",
                "ml_short_direction_cn": "短线无可靠方向",
                "ml_short_confidence": 0.0,
                "ml_short_horizon": 0,
                "ml_short_reason": "短线模型不可用",
                "ml_short_model_type_cn": "短线模型不可用",
            }

    def _safe_short_term_prediction(self, df):
        if "short_term_detector" in _failed_imports:
            return {}
        try:
            from quant_app.modules.ai.short_term_detector import short_term_detector

            return short_term_detector.analyze(df)
        except Exception as exc:
            _failed_imports.add("short_term_detector")
            logger.warning("Short-term rule branch unavailable: %s", exc)
            return {}

    def _safe_v_reversal_prediction(self, df):
        if "v_reversal_predictor" in _failed_imports:
            return {
                "v_pattern": "NONE",
                "v_pattern_cn": "无V结构",
                "v_prediction": "NEUTRAL",
                "v_prediction_cn": "短线无可靠方向",
                "v_confidence": 0.0,
                "v_reason": "V反转模型不可用",
                "v_model_type_cn": "V反转模型不可用",
                "v_model_type": "missing_or_rejected",
            }
        try:
            from quant_app.modules.ai.v_reversal_model import v_reversal_predictor

            return v_reversal_predictor.predict(df)
        except Exception as exc:
            _failed_imports.add("v_reversal_predictor")
            logger.warning("V reversal branch unavailable: %s", exc)
            return {
                "v_pattern": "NONE",
                "v_pattern_cn": "无V结构",
                "v_prediction": "NEUTRAL",
                "v_prediction_cn": "短线无可靠方向",
                "v_confidence": 0.0,
                "v_reason": "V反转模型不可用",
                "v_model_type_cn": "V反转模型不可用",
                "v_model_type": "missing_or_rejected",
            }

    def _safe_shock_prediction(self, df):
        if "shock_detector" in _failed_imports:
            return {}
        try:
            from quant_app.modules.ai.shock_detector import shock_detector

            return shock_detector.analyze(df)
        except Exception as exc:
            _failed_imports.add("shock_detector")
            logger.warning("Shock branch unavailable: %s", exc)
            return {}

    def _safe_downside_prediction(
        self,
        df_map,
        buy_first_price=None,
        sell_first_price=None,
        buy_count=0,
        sell_count=0,
    ):
        if "downside_stress_detector" in _failed_imports:
            return {}
        try:
            from quant_app.modules.ai.downside_stress import downside_stress_detector

            return downside_stress_detector.analyze(
                df_map,
                buy_first_price=buy_first_price,
                sell_first_price=sell_first_price,
                buy_count=buy_count,
                sell_count=sell_count,
            )
        except Exception as exc:
            _failed_imports.add("downside_stress_detector")
            logger.warning("Downside stress branch unavailable: %s", exc)
            return {}

    def _safe_downside_gate(self, key: str, result: dict):
        if "downside_gate_state_machine" in _failed_imports:
            return None
        try:
            from quant_app.modules.ai.downside_stress import downside_gate_state_machine

            return downside_gate_state_machine.update(key, result)
        except Exception as exc:
            _failed_imports.add("downside_gate_state_machine")
            logger.warning("Downside gate branch unavailable: %s", exc)
            return None

    def _downside_state_label(self, code: str) -> str:
        mapping = {
            "normal": "Normal",
            "downside_watch": "DownsideWatch",
            "watch_hold": "WatchHold",
            "block_hold": "BlockHold",
            "fast_drop": "FastDrop",
            "slow_bleed": "SlowBleed",
            "extreme_downtrend": "ExtremeDowntrend",
            "unknown": "Unknown",
        }
        return mapping.get(str(code), str(code))

    def _parse_window_min_max(self, window_str: str) -> tuple[int, int]:
        if not window_str or window_str == "-":
            return 0, 0
        import re
        match = re.search(r"(\d+)-(\d+)", window_str)
        if match:
            return int(match.group(1)), int(match.group(2))
        return 0, 0

    def _get_first_order_prices(self) -> tuple[float | None, float | None]:
        """Query MT5 directly to get the first (oldest) buy and sell prices for this magic and symbol."""
        try:
            positions = mt5.positions_get(symbol=self.symbol, magic=self.magic)
            if not positions:
                return None, None
            
            buys = [p for p in positions if p.type == mt5.POSITION_TYPE_BUY]
            sells = [p for p in positions if p.type == mt5.POSITION_TYPE_SELL]
            
            buy_first_price = min(buys, key=lambda x: x.time).price_open if buys else None
            sell_first_price = min(sells, key=lambda x: x.time).price_open if sells else None
            
            return buy_first_price, sell_first_price
        except Exception as exc:
            logger.debug("Failed to get first order prices from MT5: %s", exc)
            return None, None

    def _ai_status_fields(self, payload: dict = None):
        now = time.time()
        cache_key = f"{self.symbol}_ai"

        if cache_key in _ai_cache:
            cached = _ai_cache[cache_key]
            if now - cached["ts"] < 0.8:
                return cached["data"]

        try:
            df = market_data_center.get_analysis_data(self.symbol, count=300, cache_ttl=0.8)
            df_m5 = market_data_center._get_rates_df(self.symbol, "M5", count=220, start_pos=0, cache_ttl=1.2)
            df_m30 = market_data_center._get_rates_df(self.symbol, "M30", count=160, start_pos=0, cache_ttl=2.0)
            df_h1 = market_data_center._get_rates_df(self.symbol, "H1", count=160, start_pos=0, cache_ttl=3.0)

            if df is None or len(df) < 120:
                return {}
            downside_map = {"M1": df, "M5": df_m5, "M30": df_m30, "H1": df_h1}

            # Direct relative position evaluation
            buy_first_price, sell_first_price = self._get_first_order_prices()
            if payload:
                buy_count = int(payload.get("buy_count", 0))
                sell_count = int(payload.get("sell_count", 0))
            else:
                try:
                    positions = mt5.positions_get(symbol=self.symbol, magic=self.magic) or []
                    buy_count = sum(1 for p in positions if p.type == mt5.POSITION_TYPE_BUY)
                    sell_count = sum(1 for p in positions if p.type == mt5.POSITION_TYPE_SELL)
                except Exception:
                    buy_count = 0
                    sell_count = 0

            prediction = self._safe_ai_prediction(df)
            ml_short = self._safe_ml_short_prediction(df)
            short_term = self._safe_short_term_prediction(df)
            v_reversal = self._safe_v_reversal_prediction(df)
            shock = self._safe_shock_prediction(df)
            downside = self._safe_downside_prediction(
                downside_map,
                buy_first_price=buy_first_price,
                sell_first_price=sell_first_price,
                buy_count=buy_count,
                sell_count=sell_count,
            )
            gate_key = f"{self.strategy_name}:{self.symbol}:{self.magic}"
            downside_gate = self._safe_downside_gate(gate_key, downside) if downside else None

            trend_direction = prediction.get("ai_direction", "NEUTRAL")
            model_direction = prediction.get("ai_model_direction", "NEUTRAL")
            trade_direction = prediction.get("ai_trade_direction", "NEUTRAL")
            regime = prediction.get("ai_regime", "unknown")
            family = prediction.get("ai_trend_family", "ensemble_gru_trend")
            quality = prediction.get("ai_decision_quality", "unknown")
            shock_level = shock.get("shock_level", "none")
            shock_direction = shock.get("direction", "none")
            downside_state = downside.get("downside_state", "unknown")
            downside_warning = downside.get("warning", shock_level)
            downside_direction = downside.get("direction", shock_direction)
            effective_state = downside_gate.effective_state if downside_gate else downside_state
            effective_allow_add = downside_gate.allow_add if downside_gate else bool(downside.get("allow_add", True))
            effective_block = downside_gate.active_block if downside_gate else bool(downside.get("block_new_orders", False))
            hold_reason = downside_gate.hold_reason if downside_gate else "-"

            # Determine unified bidirectional shock warning
            warning_state = "none"
            warning_state_cn = "无预警"
            warning_direction = "none"
            warning_direction_cn = "无"
            expected_minutes = downside.get("expected_min", 0)
            risk_window = downside.get("risk_window", "-")
            confidence = downside.get("confidence", 0.0)

            if effective_state != "normal" and effective_state != "unknown":
                warning_state = effective_state
                warning_state_cn = self._cn_downside_state(effective_state)
                if "downside" in effective_state or effective_state in ("fast_drop", "slow_bleed", "extreme_downtrend"):
                    warning_direction = "downside"
                    warning_direction_cn = "向下"
                elif "upside" in effective_state or "slow" in effective_state:
                    warning_direction = "upside"
                    warning_direction_cn = "向上"

            win_min, win_max = self._parse_window_min_max(risk_window)

            result = {
                "ai_direction": trend_direction,
                "ai_model_direction": model_direction,
                "ai_trade_direction": trade_direction,
                "ai_regime": regime,
                "ai_trend_family": family,
                "ai_confidence": prediction.get("ai_confidence", 0.0),
                "ai_probability": prediction.get("ai_probability", 0.5),
                "ai_decision_quality": quality,
                "ai_score": prediction.get("ai_score", 0.0),
                "ai_votes": prediction.get("ai_votes", "-"),
                "ai_risk_flags": prediction.get("ai_risk_flags", "none"),
                "ai_direction_cn": self._cn_ai_direction(trend_direction),
                "ai_model_direction_cn": self._cn_ai_direction(model_direction),
                "ai_trade_direction_cn": self._cn_ai_direction(trade_direction),
                "ai_regime_cn": self._cn_ai_regime(regime),
                "ai_trend_family_cn": self._cn_ai_family(family),
                "ai_decision_quality_cn": self._cn_ai_quality(quality),
                "ai_votes_cn": self._cn_votes(prediction.get("ai_votes", "-")),
                "ai_risk_flags_cn": self._cn_risk_flags(prediction.get("ai_risk_flags", "none")),
                "current_state": self._cn_ai_direction(trend_direction),
                "current_phase": self._cn_reason(prediction),
                "current_direction": trend_direction,
                "current_impulse_state": self._cn_trade_advice(prediction, shock),
                "short_direction": short_term.get("short_direction", "NEUTRAL"),
                "short_direction_cn": short_term.get("short_direction_cn", "短线震荡"),
                "short_pattern": short_term.get("short_pattern", "UNKNOWN"),
                "short_pattern_cn": short_term.get("short_pattern_cn", "未知"),
                "short_prediction": short_term.get("short_prediction", "NEUTRAL"),
                "short_prediction_cn": short_term.get("short_prediction_cn", "短线震荡"),
                "short_confidence": short_term.get("short_confidence", 0.0),
                "short_model_type": short_term.get("short_model_type", "rule_based_uncalibrated"),
                "short_model_type_cn": short_term.get("short_model_type_cn", "规则识别-未校准"),
                "short_reason": short_term.get("short_reason", "-"),
                "short_slope8_pts": short_term.get("short_slope8_pts", 0.0),
                "short_slope20_pts": short_term.get("short_slope20_pts", 0.0),
                "ml_short_direction": ml_short.get("ml_short_direction", "NEUTRAL"),
                "ml_short_direction_cn": ml_short.get("ml_short_direction_cn", "短线无可靠方向"),
                "ml_short_confidence": ml_short.get("ml_short_confidence", 0.0),
                "ml_short_horizon": ml_short.get("ml_short_horizon", 0),
                "ml_short_reason": ml_short.get("ml_short_reason", "短线模型未训练"),
                "ml_short_model_type_cn": ml_short.get("ml_short_model_type_cn", "短线模型未训练"),
                "v_pattern": v_reversal.get("v_pattern", "NONE"),
                "v_pattern_cn": v_reversal.get("v_pattern_cn", "无V结构"),
                "v_prediction": v_reversal.get("v_prediction", "NEUTRAL"),
                "v_prediction_cn": v_reversal.get("v_prediction_cn", "短线无可靠方向"),
                "v_confidence": v_reversal.get("v_confidence", 0.0),
                "v_reason": v_reversal.get("v_reason", "V反转模型未训练"),
                "v_model_type_cn": v_reversal.get("v_model_type_cn", "V反转模型不可用"),
                "v_model_confirm_cn": self._cn_v_model_confirm(v_reversal),
                "v_reliability_cn": self._cn_v_reliability(v_reversal),
                "raw_shock_level": shock_level,
                "raw_shock_level_cn": self._cn_shock(shock_level),
                "raw_shock_confidence": shock.get("confidence", 0.0),
                "raw_shock_expected_minutes": shock.get("expected_min", 0),
                "raw_shock_direction": shock_direction,
                "raw_shock_direction_cn": self._cn_shock_direction(shock_direction),
                "downside_state": downside_state,
                "downside_state_cn": self._cn_downside_state(downside_state),
                "downside_effective_state": effective_state,
                "downside_effective_state_cn": self._cn_downside_state(effective_state),
                "downside_confidence": downside.get("confidence", 0.0),
                "downside_risk_window": downside.get("risk_window", "-"),
                "downside_expected_minutes": downside.get("expected_min", 0),
                "downside_direction": downside_direction,
                "downside_direction_cn": self._cn_shock_direction(downside_direction),
                "downside_allow_add": int(bool(downside.get("allow_add", True))),
                "downside_effective_allow_add": int(bool(effective_allow_add)),
                "downside_block_new_orders": int(bool(downside.get("block_new_orders", False))),
                "downside_effective_block_new_orders": int(bool(effective_block)),
                "downside_reason": downside.get("reason", "-"),
                "downside_hold_reason": hold_reason,
                "downside_fast_drop_score": downside.get("fast_drop_score", 0.0),
                "downside_slow_bleed_score": downside.get("slow_bleed_score", 0.0),
                "future_impulse_warning": warning_state,
                "future_impulse_warning_cn": warning_state_cn,
                "future_impulse_confidence": confidence,
                "future_impulse_expected_minutes": expected_minutes,
                "future_impulse_direction": warning_direction,
                "future_impulse_direction_cn": warning_direction_cn,
                "future_risk_window": risk_window,
                "future_impulse_window_min": win_min,
                "future_impulse_window_max": win_max,
                "future_allow_add": int(bool(effective_allow_add)),
                "updated_at": int(now),
            }

            _ai_cache[cache_key] = {"ts": now, "data": result}
            return result
        except Exception as exc:
            logger.warning("AI status generation failed: %s", exc)
            return {"updated_at": int(now)}
