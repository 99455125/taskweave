# -*- coding: utf-8 -*-
import os
import sqlite3
import logging

from contextlib import closing
from pathlib import Path

from db_server.config.db_config import Config


class SqliteDatabase:
    def __init__(self, db_path: str):
        # 处理SQLite URL格式
        if db_path.startswith('sqlite:///'):
            self.db_path = str(Path(db_path[10:]).expanduser())
        else:
            self.db_path = str(Path(db_path).expanduser())

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
        self.insights: list[str] = []

    def _init_database(self):
        """Initialize connection to the SQLite database"""
        logging.info("Initializing database connection")
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.close()

    def execute_db(self, query: str):
        """
        Execute a SQL query and return results as a list of dictionaries
        """
        logging.info(f"Executing query: {query}")
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                with closing(conn.cursor()) as cursor:
                    cursor.execute(query)

                    if query.strip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER')):
                        conn.commit()
                        affected = cursor.rowcount

                        # 特殊处理 CREATE 和 DROP 语句
                        is_schema_operation = query.strip().upper().startswith(('CREATE', 'DROP'))
                        if is_schema_operation and affected == -1:
                            # 对于模式操作，返回0作为受影响行数并添加成功标识
                            logging.info(f"Schema operation executed successfully")
                            return True, [{"operation_success": True,
                                           "operation_type": query.strip().split()[0].upper()}]

                        logging.info(f"Write query affected {affected} rows")
                        return True, [{"affected_rows": affected}]

                    results = [dict(row) for row in cursor.fetchall()]
                    logging.info(f"Read query returned {len(results)} rows")
                    return True, results
        except Exception as e:
            error = f"Database error executing sql: {query} , error: str({e})"
            logging.error(error)
            return False, error

    def preview_table(self, table_name: str) :
        try:
            # 获取表的所有列名
            column_query = f'PRAGMA table_info("{table_name}")'
            success, columns_info = self.execute_db(query=column_query)

            if not success:
                return False, {"error": f"获取表结构失败: {columns_info}"}

            if not columns_info:
                return False, {"error": f"表 {table_name} 不存在或没有列"}

            # 提取列名
            column_names = [col['name'] for col in columns_info]

            # 获取表的前五行数据
            data_query = f'SELECT * FROM "{table_name}" LIMIT 5'
            success, rows = self.execute_db(query=data_query)

            if not success:
                return False, {"error": f"获取表数据失败: {rows}"}

            return True, {
                "columns": column_names,
                "data": rows
            }

        except Exception as e:
            error_msg = f"预览表数据失败 tablename{table_name}, error: {str(e)}"
            logging.error(error_msg)
            return False, {"error": error_msg}

    def get_table_columns(self, table_name: str) :
        try:
            # 获取表的所有列名
            column_query = f'PRAGMA table_info("{table_name}")'
            success, columns_info = self.execute_db(query=column_query)

            if not success:
                return False, {"error": f"获取表结构失败: {columns_info}"}

            if not columns_info:
                return False, {"error": f"表 {table_name} 不存在或没有列"}

            # 提取列名
            column_names = [{"column_name" : col['name'], "column_type" : col['type']} for col in columns_info]

            if not success:
                return False, {"error": f"获取表数据失败: {table_name}"}

            return True, {
                "columns": column_names
            }

        except Exception as e:
            error_msg = f"预览表数据失败: {str(e)}"
            logging.error(error_msg)
            return False, {"error": error_msg}

    def drop_table(self, table_name: str) :
        """
        删除指定的数据表

        Args:
            table_name: 要删除的表名

        Returns:
            (成功标志, 操作结果信息)
        """
        try:
            # 直接执行删除表操作，使用 IF EXISTS 避免表不存在时的错误
            drop_query = f'DROP TABLE IF EXISTS "{table_name}"'
            success, result = self.execute_db(query=drop_query)

            if not success:
                raise Exception(f"删除表失败: {result}")

            return True, {"message": f"表 {table_name} 删除操作已完成"}

        except Exception as e:
            logging.error(f"删除表失败: {str(e)}")
            raise e


def execute_sql(sql: str, task_id: str):
    """
    Execute a SQL STATEMENT and return results as a list of dictionaries
    """
    db_path = os.path.abspath(os.path.join(Config.SQLALCHEMY_DATABASE_DIRPATH, f"task_{task_id}.db_server"))
    db = SqliteDatabase(db_path)
    return db.execute_db(query=sql)


def get_table_json(table_name: str, task_id: str) :
    """
    Execute a SQL STATEMENT and return results as a list of dictionaries
    """
    db_path = os.path.abspath(os.path.join(Config.SQLALCHEMY_DATABASE_DIRPATH, f"task_{task_id}.db_server"))
    db = SqliteDatabase(db_path)
    preview_success, data = db.preview_table(table_name=table_name)
    if preview_success and data is not None:
        data = convert_to_serializable(data)
    return preview_success, data

def convert_to_serializable(data):
    """递归地将数据转换为可序列化的类型"""
    import numpy as np

    if isinstance(data, bytes):
        return data.decode('utf-8', errors='replace')
    elif isinstance(data, dict):
        return {key: convert_to_serializable(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [convert_to_serializable(item) for item in data]
    elif isinstance(data, np.integer):
        return int(data)
    elif isinstance(data, np.floating):
        return float(data)
    elif isinstance(data, np.ndarray):
        return convert_to_serializable(data.tolist())
    return data

def drop_table(table_name: str, task_id: str) :
    """
    删除指定的数据表

    Args:
        table_name: 要删除的表名
        task_id: 任务ID

    Returns:
        (成功标志, 操作结果信息)
    """
    db_path = os.path.abspath(os.path.join(Config.SQLALCHEMY_DATABASE_DIRPATH, f"task_{task_id}.db_server"))
    db = SqliteDatabase(db_path)
    return db.drop_table(table_name=table_name)


def drop_db(task_id: str) :
    """
    删除指定任务的整个数据库文件

    Args:
        task_id: 任务ID

    Returns:
        (成功标志, 操作结果信息)
    """
    try:
        db_path = os.path.abspath(os.path.join(Config.SQLALCHEMY_DATABASE_DIRPATH, f"task_{task_id}.db_server"))

        # 检查文件是否存在
        if os.path.exists(db_path):
            # 删除文件
            os.remove(db_path)
        return True, {"message": f"数据库文件已成功删除: {db_path}"}

    except Exception as e:
        error_msg = f"删除数据库文件失败: {str(e)}"
        logging.error(error_msg)
        return False, {"error": error_msg}


def get_table_columns(table_name: str, task_id: str) :
    """
    获取指定表的列信息

    Args:
        table_name: 表名
        task_id: 任务ID

    Returns:
        (成功标志, 包含列名和类型的字典)
    """
    db_path = os.path.abspath(os.path.join(Config.SQLALCHEMY_DATABASE_DIRPATH, f"task_{task_id}.db_server"))
    db = SqliteDatabase(db_path)
    return db.get_table_columns(table_name=table_name)