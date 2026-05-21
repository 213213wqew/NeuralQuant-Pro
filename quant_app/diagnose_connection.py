import os
import sys

# 环境路径对齐
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from quant_app.core.mt5_client import mt5_client
from quant_app.core.logger import get_logger

logger = get_logger("Diagnose")

def diagnose():
    logger.info("开始设备链路诊断...")
    
    # 1. 测试连接 (自动处理路径)
    if not mt5_client.connect():
        logger.error("MT5 链路初始化失败，请检查 .env 中的 MT5_PATH 是否正确。")
        return

    # 2. 获取账户状态
    acc = mt5_client.get_account_stat()
    if acc:
        logger.info(f"「连接成功」")
        logger.info(f"  账户登录: {acc['login']}")
        logger.info(f"  所属服务器: {acc['server']}")
        logger.info(f"  账户余额: {acc['balance']} {acc['currency']}")
        logger.info(f"  账户净值: {acc['equity']}")
        logger.info(f"  交易允许: {'YES' if acc['trade_allowed'] else 'NO (请在MT5终端开启 [算法交易] 按钮)'}")
    else:
        logger.warning("已连接但无法拉取账户信息。")

    # 3. 检查市场报价
    tick = mt5_client.get_market_data("XAUUSD.c")
    if tick:
        logger.info(f"「报价同步」XAUUSD.c Bid: {tick['bid']} | Ask: {tick['ask']}")
    else:
        logger.error("无法获取报价，请检查品种名是否正确。")

    mt5_client.disconnect()
    logger.info("测试结束，链路已关闭。")

if __name__ == "__main__":
    diagnose()
