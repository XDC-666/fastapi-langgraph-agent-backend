"""统一日志配置：启动时调用一次 setup_logging()，其余模块直接 getLogger 即可。"""
import logging
import sys

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = "INFO") -> None:
    """配置根 logger 输出到 stdout，便于容器日志采集。"""
    root = logging.getLogger()
    # 避免重复添加 handler（例如测试中被多次调用）
    if root.handlers:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root.setLevel(level.upper())
    root.addHandler(handler)

    # 第三方库降噪
    for noisy in ("httpx", "httpcore", "openai", "urllib3", "chromadb"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
