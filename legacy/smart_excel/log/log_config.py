# -*- coding: utf-8 -*-
import os
import logging
from logging.handlers import RotatingFileHandler

from log.log_websocket_server import QueueLogHandler


def setup_logging():
    excel_base_dir_path = os.environ.get('EXCEL_BASE_DIR', os.path.dirname(os.path.dirname(__file__)))
    log_dir = os.path.join(excel_base_dir_path, 'logs')
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 日志格式，包含文件名和行号
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s')

    # 创建处理器
    handler = RotatingFileHandler(
        os.path.join(log_dir, 'app.log'),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding = 'utf-8'
    )
    handler.setFormatter(formatter)

    # 错误日志处理器
    error_handler = RotatingFileHandler(
        os.path.join(log_dir, 'error.log'),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding = 'utf-8'
    )
    error_handler.setFormatter(formatter)
    error_handler.setLevel(logging.ERROR)  # 只记录错误级别

    # 添加控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # 添加 WebSocket 日志处理器
    websocket_handler = QueueLogHandler()
    websocket_handler.setFormatter(formatter)  # 你也可以发送JSON

    # 配置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(websocket_handler)


def save_logger_config():
    root = logging.getLogger()
    return {
        'level': root.level,
        'handlers': list(root.handlers),
        'disabled': root.disabled
    }


def restore_logger_config(config):
    root = logging.getLogger()
    root.setLevel(config['level'])

    # 清除当前处理器
    for handler in list(root.handlers):
        root.removeHandler(handler)

    # 添加保存的处理器
    for handler in config['handlers']:
        root.addHandler(handler)

    root.disabled = config['disabled']