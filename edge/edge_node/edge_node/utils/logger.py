"""日志模块：统一日志格式，便于后续接入云端日志分析

所有子 logger（edge_node.mqtt / edge_node.main / ...）通过日志传播
输出到父 logger edge_node 的 handler，确保全模块日志统一可见。
"""
import logging
import sys

_BASE_LOGGER_NAME = 'edge_node'
_configured = False


def get_logger(name: str = _BASE_LOGGER_NAME) -> logging.Logger:
    global _configured
    if not _configured:
        base = logging.getLogger(_BASE_LOGGER_NAME)
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt='[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )
        handler.setFormatter(formatter)
        if not base.handlers:
            base.addHandler(handler)
        base.setLevel(logging.INFO)
        base.propagate = False
        _configured = True
    return logging.getLogger(name)
