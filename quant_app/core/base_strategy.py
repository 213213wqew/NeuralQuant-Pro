from abc import ABC, abstractmethod

class BaseStrategy(ABC):
    """
    所有交易策略的基类。
    定义了策略运行所需的基本接口。
    """
    def __init__(self, name: str, symbol: str):
        self.name = name
        self.symbol = symbol
        self.is_running = False

    @abstractmethod
    def start(self):
        """启动策略"""
        self.is_running = True
        pass

    @abstractmethod
    def stop(self):
        """停止策略"""
        self.is_running = False
        pass

    @abstractmethod
    def run_iteration(self):
        """执行单次迭代逻辑（主循环中调用）"""
        pass
