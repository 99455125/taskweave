# -*- coding: utf-8 -*-
import asyncio

import enviroment_config
import os
import logging
import socket
import webbrowser
from threading import Timer
import threading

from flask_migrate import upgrade, migrate, init, stamp
from app.app import create_app
from log.log_config import setup_logging, restore_logger_config, save_logger_config
from log.log_websocket_server import start_websocket_server

# 设置日志目录
setup_logging()

# 创建app
app = create_app()

# 获取数据库迁移目录
migrations_dir = os.path.join(enviroment_config.excel_base_dir_path, 'migrations')
# 数据库自动升级
def migrate_db():
    # 如果 migrations 目录不存在，先初始化
    if not os.path.exists(migrations_dir):
        init(directory=migrations_dir)
        stamp(directory=migrations_dir)
    # 自动生成迁移脚本®
    migrate(directory=migrations_dir, message="auto migrate")
    # 自动升级数据库
    upgrade(directory=migrations_dir)


# 初始化数据库迁移
with app.app_context():
    logging.info("数据库目录：%s", migrations_dir)
    # 保存日志配置, migrate组件会重置全局日志
    original_config = save_logger_config()
    migrate_db()
    # 恢复日志配置
    restore_logger_config(original_config)
    logging.info("数据库结构已自动更新")

def open_browser(port=5000):
    """在默认浏览器中打开指定的URL。"""
    webbrowser.open_new(f"http://127.0.0.1:{port}/index.html")

def run_websocket_server_thread(socket_port):
    asyncio.run(start_websocket_server(socket_port))

# 运行 Flask 应用
if __name__ == '__main__':
    logging.info("Flask 应用smart_excel已开始启动")
    start_port = 5000
    end_port = 5009
    port_found = False
    for port in range(start_port, end_port + 1):
        try:
            # 兼容windows debug模式
            if not port_found:
                # 尝试创建一个套接字并绑定到端口，以检查端口是否可用
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(("127.0.0.1", port))
                # 如果绑定成功，说明端口可用
                logging.info(f"尝试在端口 {port} 启动应用...")
                Timer(2, open_browser, args=(port,)).start()

            ws_thread = threading.Thread(target=run_websocket_server_thread, args=(port+10,), daemon=True)
            ws_thread.start()

            app.run(port=port, debug=False)
            port_found = True
            break
        except OSError as e:
            if e.errno == 98 or e.errno == 48 or e.errno == 10048:
                logging.info(f"端口 {port} 已被占用，尝试下一个端口...")
            else:
                logging.error(f"在端口 {port} 启动应用时发生未知错误: {e}")
                break
        except Exception as e:
            logging.error(f"在端口 {port} 启动应用时发生预料之外的错误: {e}")
            break


    if not port_found:
        logging.error(f"无法在端口 {start_port}-{end_port} 范围内找到可用端口启动应用。")

    logging.info("Flask 应用smart_excel已终止")