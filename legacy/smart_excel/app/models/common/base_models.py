from datetime import datetime

from db_server.db_init import db as db



class BaseModel(db.Model):
    __abstract__ = True
    create_time = db.Column(db.DateTime, default=datetime.now)
    update_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)