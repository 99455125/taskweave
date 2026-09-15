# -*- coding: utf-8 -*-
import logging


def init_bp(app):
    """初始化所有蓝图"""
    from app.routes.routes_task import task_bp
    from app.routes.routes_step import step_bp
    from app.routes.routes_task_file import task_file_bp
    from app.routes.routes_task_table import task_table_bp

    # 注册所有蓝图
    app.register_blueprint(task_bp)
    app.register_blueprint(step_bp)
    app.register_blueprint(task_file_bp)
    app.register_blueprint(task_table_bp)
    logging.info("蓝图已注册")
