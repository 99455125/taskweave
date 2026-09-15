# -*- coding: utf-8 -*-
import os
main_db = 'task.db_server'

excel_base_dir_path = os.environ.get('EXCEL_BASE_DIR', os.path.dirname(os.path.dirname(__file__)))
sqlite_db_path = os.path.join(excel_base_dir_path, 'db')
if not os.path.exists(sqlite_db_path):
    os.makedirs(sqlite_db_path)

class Config:
    SQLALCHEMY_DATABASE_DIRPATH = sqlite_db_path
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.abspath(os.path.join(SQLALCHEMY_DATABASE_DIRPATH, main_db))
    SQLALCHEMY_TRACK_MODIFICATIONS = False