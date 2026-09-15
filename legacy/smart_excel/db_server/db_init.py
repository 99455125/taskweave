# -*- coding: utf-8 -*-

from flask_sqlalchemy import SQLAlchemy

from db_server.config.db_config import Config

db = SQLAlchemy()


def db_init_app(app):
    app.config['SQLALCHEMY_DATABASE_URI'] = Config.SQLALCHEMY_DATABASE_URI
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = Config.SQLALCHEMY_TRACK_MODIFICATIONS
    db.init_app(app)
    return db
