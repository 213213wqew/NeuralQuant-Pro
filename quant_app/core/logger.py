import atexit
import logging
import os
import sys
from datetime import datetime
from logging.handlers import QueueHandler, QueueListener
from queue import Queue

# 确保日志目录存在（统一放在项目根目录下的 logs 目录中）。
if getattr(sys, "frozen", False):
    CWD = os.path.dirname(os.path.abspath(sys.executable))
else:
    CWD = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
log_dir = os.path.join(CWD, "logs")
os.makedirs(log_dir, exist_ok=True)

log_file = os.path.join(log_dir, f"quant_{datetime.now().strftime('%Y%m%d')}.log")

# 主日志格式
log_format = logging.Formatter(
    "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)


class FletLogHandler(logging.Handler):
    """把日志消息推给 Flet 界面层。"""

    def __init__(self):
        super().__init__()
        self.callback = None

    def emit(self, record):
        if not self.callback:
            return
        msg = self.format(record)
        self.callback(msg, record.levelname)


_listener_registry = {}


def _register_listener(name, listener):
    """注册异步监听器，确保进程退出时统一安全关闭。"""
    old_listener = _listener_registry.get(name)
    if old_listener and old_listener is not listener:
        old_listener.stop()
    _listener_registry[name] = listener
    return listener


def _shutdown_all_listeners():
    for listener in list(_listener_registry.values()):
        try:
            listener.stop()
        except Exception:
            pass
    _listener_registry.clear()


atexit.register(_shutdown_all_listeners)


# 主日志的后端处理器全部放到异步监听器中，主线程只负责把日志对象塞进队列。
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_format)

file_handler = logging.FileHandler(log_file, encoding="utf-8")
file_handler.setFormatter(log_format)

flet_handler = FletLogHandler()
flet_handler.setFormatter(log_format)

_main_queue = Queue(-1)
_main_listener = QueueListener(
    _main_queue,
    console_handler,
    file_handler,
    flet_handler,
    respect_handler_level=True,
)
_main_listener.start()
_register_listener("main", _main_listener)

logger = logging.getLogger("A-Quant")
logger.setLevel(logging.INFO)
logger.propagate = False
logger.handlers.clear()
logger.addHandler(QueueHandler(_main_queue))


def get_logger(name):
    """获取带命名空间的子 Logger。"""
    child_logger = logger.getChild(name)
    child_logger.propagate = True
    return child_logger


def get_daily_file_logger(name, subdir="verify", prefix="verify"):
    """返回一个只写入独立文件的异步日志器，用于策略验证日志。"""
    safe_subdir = str(subdir or "verify").strip().replace("/", "_").replace("\\", "_")
    safe_prefix = str(prefix or "verify").strip().replace("/", "_").replace("\\", "_")
    target_dir = os.path.join(log_dir, safe_subdir)
    os.makedirs(target_dir, exist_ok=True)

    target_file = os.path.join(
        target_dir,
        f"{safe_prefix}_{datetime.now().strftime('%Y%m%d')}.log",
    )
    logger_name = f"A-Quant.File.{name}.{safe_subdir}.{safe_prefix}"
    listener_name = f"{logger_name}.listener"

    file_logger = logging.getLogger(logger_name)
    file_logger.setLevel(logging.INFO)
    file_logger.propagate = False

    if not getattr(file_logger, "_async_logger_ready", False):
        queue = Queue(-1)
        handler = logging.FileHandler(target_file, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        listener = QueueListener(queue, handler, respect_handler_level=True)
        listener.start()
        _register_listener(listener_name, listener)

        file_logger.handlers.clear()
        file_logger.addHandler(QueueHandler(queue))
        file_logger._async_logger_ready = True
        file_logger._async_log_file = target_file
    elif getattr(file_logger, "_async_log_file", "") != target_file:
        queue = Queue(-1)
        handler = logging.FileHandler(target_file, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        listener = QueueListener(queue, handler, respect_handler_level=True)
        listener.start()
        _register_listener(listener_name, listener)

        file_logger.handlers.clear()
        file_logger.addHandler(QueueHandler(queue))
        file_logger._async_log_file = target_file

    return file_logger
