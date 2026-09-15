# -*- coding: utf-8 -*-
from flask_migrate import Migrate

from app.models.models_init import init_models
from app.routes.routes_init import init_bp
from db_server.db_init import db_init_app, db
from flask import Flask, send_from_directory

import logging

# Initialize Flask app and database
app = Flask(__name__, static_folder='static', static_url_path='/')

def create_app():
    from app.config.app_config import Config
    app.config.from_object(Config)
    # 导入db模型
    init_models()
    # 导入db
    db_init_app(app)

    # 初始化更新数据库模型
    Migrate(app, db)

    # 注册蓝图
    init_bp(app)

    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve_vue_app(path):
        return send_from_directory(app.static_folder, 'index.html')


    # 打印所有的api
    for rule in app.url_map.iter_rules():
        logging.info({
            'endpoint': rule.endpoint,
            'methods': list(rule.methods),
            'rule': str(rule)
        })

    return app
