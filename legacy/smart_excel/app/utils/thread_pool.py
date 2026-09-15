# -*- coding: utf-8 -*-
from concurrent.futures import ThreadPoolExecutor
import threading
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

from db_server.config.db_config import Config

# 创建独立的 SQLAlchemy 引擎和会话工厂
engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
Session = scoped_session(sessionmaker(bind=engine))

class ThreadLocalStorage(threading.local):
    """线程本地存储类，用于在线程间隔离数据"""
    pass

class ThreadPoolManager:
    """线程池管理器，提供线程池功能并集成线程本地存储"""

    def __init__(self, max_workers=5):
        """
        初始化线程池和线程本地存储
        :param max_workers: 最大工作线程数
        """
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._thread_local = ThreadLocalStorage()
        logging.info(f"线程池初始化完成，最大工作线程数: {max_workers}")

    def submit(self, func, *args, **kwargs):
        """
        提交任务到线程池
        :param func: 要执行的函数
        :param args: 位置参数
        :param kwargs: 关键字参数
        :return: Future对象
        """
        return self.executor.submit(func, *args, **kwargs)

    def shutdown(self, wait=True):
        """
        关闭线程池
        :param wait: 是否等待所有线程完成
        """
        self.executor.shutdown(wait=wait)
        logging.info("线程池已关闭")

    def __getattr__(self, name):
        """
        获取线程本地存储中的属性
        :param name: 属性名
        :return: 属性值
        """
        return getattr(self._thread_local, name)

    def __setattr__(self, name, value):
        """
        设置属性，如果不是executor或_thread_local，则存储在线程本地存储中
        :param name: 属性名
        :param value: 属性值
        """
        if name in ('executor', '_thread_local'):
            object.__setattr__(self, name, value)
        else:
            setattr(self._thread_local, name, value)

# 全局线程池实例
thread_pool = ThreadPoolManager()
local_storage = ThreadLocalStorage()