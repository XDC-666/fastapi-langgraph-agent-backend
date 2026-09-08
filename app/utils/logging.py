"""统一日志配置。

在应用启动时调用 `setup_logging()` 完成一次初始化，
其余模块只需 `logger = logging.getLogger(__name__)` 即可使用。
"""
import logging
import sys

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = "INFO") -> None:
    """配置根 logger：输出到 stdout，便于 Docker / 容器日志采集。"""
    root = logging.getLogger()
    # 避免重复添加 handler（例如测试中被多次调用）
    if root.handlers:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))

    root.setLevel(level.upper())
    root.addHandler(handler)

    # 第三方库过于吵闹，单独降噪
    for noisy in ("httpx", "httpcore", "openai", "urllib3", "chromadb"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
