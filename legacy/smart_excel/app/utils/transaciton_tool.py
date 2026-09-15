import functools
from flask import Response
from db_server.db_init import db
import json
import logging




def route_transactional(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)

            # 检查返回结果类型
            if isinstance(result, dict):
                # 假设返回的是字典格式，检查code字段
                if result.get('code') == 200:
                    db.session.commit()
                    logging.info("事务提交成功")
                else:
                    db.session.rollback()
                    logging.info(f"状态码非200，事务回滚: {result.get('code')}")
            elif isinstance(result, Response):
                # 如果是Flask Response对象
                try:
                    data = json.loads(result.get_data(as_text=True))
                    if data.get('code') == 200:
                        db.session.commit()
                        logging.info("事务提交成功")
                    else:
                        db.session.rollback()
                        logging.info(f"状态码非200，事务回滚: {data.get('code')}")
                except Exception as e:
                    # 无法解析返回结果，默认提交
                    db.session.commit()
                    logging.error(f"无法解析响应内容，默认提交事务: {e}")
            else:
                # 其他类型响应，默认提交
                db.session.commit()
                logging.info("默认提交事务")

            return result
        except Exception as e:
            db.session.rollback()
            logging.error(f"执行出现异常，事务回滚: {str(e)}")
            raise e

    return wrapper