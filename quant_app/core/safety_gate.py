from quant_app.core.logger import get_logger

logger = get_logger("SafetyGate")

class SafetyGate:
    def __init__(self, max_daily_loss_percent=2.0):
        self.max_daily_loss_percent = max_daily_loss_percent

    def check_kill_switch(self, account_info):
        """
        [全局生死线] 检查是否触及每日熔断红线
        这是最后一道防线，用于保护账户不被极端行情击穿。
        """
        if account_info is None:
            return False
            
        # 利润为负时计算亏损比例
        if account_info['profit'] < 0:
            balance = account_info['balance']
            if balance <= 0: return True # 账户已空，触发熔断
            
            loss_percent = (abs(account_info['profit']) / balance) * 100
            if loss_percent >= self.max_daily_loss_percent:
                logger.critical(f"触及全局熔断线! 当前亏损比例: {loss_percent:.2f}% >= 设定阈值: {self.max_daily_loss_percent}%")
                return True
                
        return False

    def check_global_risk(self, account_info):
        """
        [全局状态检查] 检查风控状态，返回是否允许交易
        """
        if not account_info:
            return False, "无法获取账户信息"
            
        if self.check_kill_switch(account_info):
            return False, "触及全局熔断红线，交易已禁止"
            
        if account_info.get('margin_level', 1000) < 100:
            return False, "预付款比例过低 (<100%)，交易受限"
            
        return True, "账户状态正常"

safety_gate = SafetyGate()
