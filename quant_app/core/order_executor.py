import MetaTrader5 as mt5
import time

from quant_app.core.logger import get_logger
from quant_app.core.mt5_client import mt5_client

logger = get_logger("OrderExecutor")


class OrderExecutor:
    def place_order(
        self,
        symbol,
        order_type,
        volume=0.01,
        sl_price=None,
        tp_price=None,
        magic=10086,
        comment="A-Quant",
    ):
        # 统一走一个底层发送函数，避免市价单和后续扩展单据分两套逻辑。
        return self._send_single_request(
            symbol,
            order_type,
            volume,
            sl_price,
            tp_price,
            magic=magic,
            comment=comment,
        )

    def close_position(self, ticket):
        # volume=None 表示整单平仓。
        return self._close_position_volume(ticket, None)

    def partial_close_position(self, ticket, volume):
        # 部分平仓是新策略的核心能力，L16 修复逻辑会大量依赖这里。
        return self._close_position_volume(ticket, volume)

    def close_all_fast(self, symbol, magic):
        """
        高性能批量平仓：不进行串行等待，极速发出所有平仓请求。
        """
        if not mt5_client.ensure_connected():
            return {"status": "error", "message": "MT5 terminal disconnected"}

        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return {"status": "success", "count": 0}

        target_positions = [p for p in positions if p.magic == magic]
        if not target_positions:
            return {"status": "success", "count": 0}

        logger.info(f"开启极速平仓模式：目标订单数={len(target_positions)}")
        
        # 预先获取成交模式，减少循环内的开销
        filling_mode = self._get_filling_mode(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return {"status": "error", "message": "Unable to fetch quote"}

        results_ok = []
        for pos in target_positions:
            # 构造平仓请求
            close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
            price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
            
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": pos.volume,
                "type": close_type,
                "price": price,
                "position": pos.ticket,
                "deviation": 20,
                "magic": pos.magic,
                "comment": "fast_close_all",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling_mode,
            }
            # 发送指令并检查结果
            res = mt5.order_send(request)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                results_ok.append(pos.ticket)
            else:
                code = res.retcode if res else "Err"
                logger.error(f"极速平仓单笔失败: ticket={pos.ticket}, retcode={code}")
            
        logger.info(f"极速平仓执行完毕，成功: {len(results_ok)}/{len(target_positions)}")
        return {"status": "success", "count": len(results_ok)}

    def close_all_by_magic(self, symbol, magic):
        return self.close_all_fast(symbol, magic)

    def close_all_for_symbol(self, symbol):
        """
        紧急全平：关闭指定品种的所有未平仓订单（无论 Magic 多少）。
        """
        if not mt5_client.ensure_connected():
            return {"status": "error", "message": "MT5 terminal disconnected"}

        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return {"status": "success", "count": 0}

        logger.warning(f"开启极速【全平】模式：品种={symbol}, 目标订单数={len(positions)}")
        results_ok = []
        for pos in positions:
            res = self.close_position(pos.ticket)
            if res.get("status") == "success":
                results_ok.append(pos.ticket)
            
        logger.warning(f"极速全平执行完毕，成功: {len(results_ok)}/{len(positions)}")
        return {"status": "success", "count": len(results_ok)}

    def close_by_opposite(self, symbol):
        """
        对冲解仓（CloseBy 冲抵）：利用 MT5 特有的双向对冲平仓机制，
        将品种的多单与空单两两冲抵，完全免除点差成本。
        """
        if not mt5_client.ensure_connected():
            return {"status": "error", "message": "MT5 terminal disconnected"}

        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return {"status": "success", "count": 0}

        buys = [p for p in positions if p.type == mt5.ORDER_TYPE_BUY]
        sells = [p for p in positions if p.type == mt5.ORDER_TYPE_SELL]

        if not buys or not sells:
            return {"status": "error", "message": "没有相反方向的持仓订单，无法进行 CloseBy 冲抵。"}

        logger.warning(f"开启对冲冲抵解仓 (CloseBy)：品种={symbol}, 多头={len(buys)}笔, 空头={len(sells)}笔")
        
        # 排序以保证按订单顺序配对
        buys.sort(key=lambda x: x.ticket)
        sells.sort(key=lambda x: x.ticket)

        count = 0
        
        while buys and sells:
            b_pos = buys[0]
            s_pos = sells[0]

            request = {
                "action": mt5.TRADE_ACTION_CLOSE_BY,
                "position": b_pos.ticket,
                "position_by": s_pos.ticket,
                "symbol": symbol,
                "deviation": 20,
            }
            res = mt5.order_send(request)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"CloseBy 冲抵成功: BUY #{b_pos.ticket} 与 SELL #{s_pos.ticket}")
                count += 1
                
                # CloseBy 是原子冲抵。冲抵后订单要么消失，要么留存剩余部分。
                # 重新拉取一次持仓状态更新排序，确保下一轮配对绝对精确
                time.sleep(0.15)
                positions = mt5.positions_get(symbol=symbol)
                if not positions:
                    break
                buys = [p for p in positions if p.type == mt5.ORDER_TYPE_BUY]
                sells = [p for p in positions if p.type == mt5.ORDER_TYPE_SELL]
                buys.sort(key=lambda x: x.ticket)
                sells.sort(key=lambda x: x.ticket)
            else:
                code = res.retcode if res else "Err"
                logger.error(f"CloseBy 冲抵失败: BUY #{b_pos.ticket} 与 SELL #{s_pos.ticket}, retcode={code}")
                # 失败的话退出，防止死循环
                break

        return {"status": "success", "count": count}

    def _close_position_volume(self, ticket, close_volume):
        if not mt5_client.ensure_connected():
            return {"status": "error", "message": "MT5 terminal disconnected"}

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            logger.error(f"未找到需要平仓的持仓，ticket={ticket}")
            return {"status": "error", "message": f"Position {ticket} not found"}

        pos = positions[0]
        symbol = pos.symbol
        # 部分平仓不能超过当前持仓量，所以这里做一次上限截断。
        requested_volume = pos.volume if close_volume is None else min(close_volume, pos.volume)
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return {"status": "error", "message": "Unable to fetch quote"}

        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": requested_volume,
            "type": close_type,
            "price": price,
            "position": ticket,
            "deviation": 20,
            "magic": pos.magic,
            "comment": "partial_close" if close_volume is not None else "close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._get_filling_mode(symbol),
        }

        # 先按经纪商推荐的成交模式发送，失败后自动降级重试。
        result = self._send_with_fallback(request, symbol, close_type)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            code = result.retcode if result else "Err"
            logger.error(f"平仓失败，ticket={ticket}, 手数={requested_volume}, retcode={code}")
            return {"status": "error", "message": f"Close failed code: {code}"}

        action_name = "部分平仓成功" if close_volume is not None else "全部平仓成功"
        logger.info(f"{action_name}，ticket={ticket}, 手数={requested_volume}")
        return {
            "status": "success",
            "ticket": result.order,
            "closed_volume": requested_volume,
        }

    def _get_filling_mode(self, symbol):
        # 不同经纪商支持的成交模式不同，这里做自动探测。
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            return mt5.ORDER_FILLING_IOC

        filling_mode = symbol_info.filling_mode
        if filling_mode & 1:
            return mt5.ORDER_FILLING_FOK
        if filling_mode & 2:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def _send_single_request(
        self,
        symbol,
        order_type,
        volume,
        sl_price,
        tp_price,
        action_type=mt5.TRADE_ACTION_DEAL,
        price=None,
        magic=10086,
        comment="A-Quant",
    ):
        if not mt5_client.ensure_connected():
            return {"status": "error", "message": "MT5 terminal disconnected"}

        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            return {"status": "error", "message": "Unable to fetch symbol info"}

        request = {
            "action": action_type,
            "symbol": symbol,
            "volume": round(volume, 2),
            "type": mt5.ORDER_TYPE_BUY if order_type == "BUY" else mt5.ORDER_TYPE_SELL,
            "magic": magic,
            "comment": comment,
            "deviation": 20,
            "type_time": mt5.ORDER_TIME_GTC,
        }

        if sl_price:
            request["sl"] = float(sl_price)
        if tp_price:
            request["tp"] = float(tp_price)

        if action_type == mt5.TRADE_ACTION_PENDING:
            request["type"] = mt5.ORDER_TYPE_BUY_LIMIT if order_type == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT
            request["type_filling"] = mt5.ORDER_FILLING_RETURN
            request["price"] = float(price)
            result = mt5.order_send(request)
        else:
            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                return {"status": "error", "message": "Unable to fetch quote"}
            request["price"] = tick.ask if order_type == "BUY" else tick.bid
            request["type_filling"] = self._get_filling_mode(symbol)
            result = self._send_with_fallback(request, symbol, request["type"])

        # 统一按 retcode 判断成败，方便上层策略做状态机控制。
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            code = result.retcode if result else "Err"
            logger.error(f"开仓失败，方向={order_type}, 品种={symbol}, retcode={code}")
            return {"status": "error", "message": f"Order failed code: {code}"}

        logger.info(f"开仓成功，方向={order_type}, 品种={symbol}, ticket={result.order}, 注释={comment}")
        return {"status": "success", "ticket": result.order, "price": request.get("price")}

    def _send_with_fallback(self, request, symbol, order_type):
        # 某些经纪商在指定成交模式下会返回 10030，这里自动切换模式重试。
        result = mt5.order_send(request)
        if result and result.retcode == 10030:
            for mode in [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]:
                if mode == request["type_filling"]:
                    continue
                request["type_filling"] = mode
                tick = mt5.symbol_info_tick(symbol)
                if not tick:
                    break
                request["price"] = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
                result = mt5.order_send(request)
                if result and result.retcode != 10030:
                    break
        return result


order_executor = OrderExecutor()


