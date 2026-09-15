import json
import logging

import db_server.db_init
from app.models.biz.step_models import Step, StepUseTable
from app.models.biz.task_models import Task
from app.models.biz.task_table_models import TaskTable
from app.utils.db_session_tool import inject_db_session
from app.utils.thread_pool import local_storage
from deepseek.client.deepseek_http_client import DeepseekHttpClient
from deepseek.client.deepseek_web_client import DeepseekWebHttpClient
from deepseek.prompt import prompt_step
from deepseek.tools.http_response_tool import LLMResponseParser
from tools.db.db_tool import get_table_json, drop_table, execute_sql, get_table_columns

deepseek_client = DeepseekHttpClient()

class StepService:

    @staticmethod
    @inject_db_session
    def clear_step(step_id, session=None):
        step = session.query(Step).get(step_id)
        step.is_success = None
        step.step_sql = None

        task_table = session.query(TaskTable).filter_by(step_id=step_id).first()

        # 没有task_table或者task_table的表名与当前步骤的表名不一致 也要删除旧的表
        # 主要防止大模型生成的表名与用户的不一致， 清理没有task_table的情况
        if not task_table or step.table_name != task_table.table_name:
            # 如果步骤表名与任务表名不一致，删除旧的表
            drop_table(table_name=step.table_name, task_id=step.task_id)

        if task_table:
            drop_table(table_name=task_table.table_name,
                       task_id=task_table.task_id)
            session.delete(task_table)

    @staticmethod
    @inject_db_session
    def execute_step(step_id, session=None):

        try:
            # 当前执行步骤
            step = session.query(Step).get(step_id)

            # 步骤执行记录校验
            if not step:
                return False, {"error": "步骤记录不存在"}

            task = session.query(Task).get(step.task_id)
            # 任务执行记录校验
            if not task:
                return False, {"error": "任务记录不存在"}

            # 锁定任务
            if task.task_status == '01':
                task.task_status = '02'

            # 调试大模型
            if not step.step_sql:
                return StepService.debug_step(session, step, task)
            # 执行上次的步骤SQL
            else:
                return StepService.execute_step_sql(session, step, task)
        except Exception as e:
            logging.error(f"执行步骤逻辑异常: {str(e)}")
            if hasattr(local_storage, 'session') and local_storage.session:
                step = local_storage.session.query(Step).get(step_id)
                step.is_success = False
                step.step_sql = None
            return False, {"error": str(e)}
        finally:
            # 在finally中重新查询步骤执行对象，而不是使用可能已过期的全局变量
            if hasattr(local_storage, 'session') and local_storage.session:
                local_storage.session.commit()

    @staticmethod
    def execute_step_sql(session, step, task):
        step_success, result = execute_sql(sql=step.step_sql, task_id=task.task_id)
        if not step_success:
            return False, {"error": result}
        # sql执行成功处理
        get_table_success, table_json = get_table_json(table_name=step.table_name,
                                                       task_id=step.task_id)
        # 处理表数据
        if not get_table_success:
            return False, {'error': '预览表失败'}
        else:
            table_json = json.dumps(table_json, ensure_ascii=False)
            step.is_success = True
        task_table = session.query(TaskTable).filter_by(task_id=step.task_id, step_id=step.step_id).first()
        if not task_table:
            return False, {'error': '原执行结果不存在'}
        task_table.table_preview_json = table_json
        return True, {"table_json": table_json}

    @staticmethod
    def debug_step(session, step, task):
        table_columns = StepService.get_step_use_table_columns(session, step)
        user_prompt = prompt_step.PROMPT.format(table_name=step.table_name, step_content=step.step_content, table_columns=json.dumps(table_columns, ensure_ascii=False))
        messages = [
            {"role": "user", "content": user_prompt}
        ]
        logging.info(f"调用大模型请求内容: {messages}")
        response_content = deepseek_client.chat_completion(
            messages=messages
        )
        logging.info(f"大模型返回: {response_content}")
        answer_type, answer_data = LLMResponseParser.parse_response(response_content)
        # 调用失败
        if answer_type != 'sql':
            logging.error(f"请修改提示词后重试， 大模型返回：{answer_data.get('error_msg', '大模型返回格式不正确, 请重试')}")
            return False, {"error": f"请修改提示词后重试， 大模型返回：{answer_data.get('error_msg', '大模型返回格式不正确, 请重试')}"}

        sql_text = answer_data.get('sql_text')
        if not sql_text.strip().upper().startswith(('CREATE', 'ALTER')):
            logging.error(f"请重新执行或修改提示词后重试， 大模型返回sql：{sql_text}")
            return False, {"error": f"请重新执行或修改提示词后重试， 大模型返回sql：{sql_text}"}

        step_success, result = execute_sql(sql=sql_text, task_id=task.task_id)
        if not step_success:
            logging.error(f"执行sql报错，请重试。 sql: {sql_text}  sql报错: {result}")
            return False, {"error": f"执行sql报错，请重试。 sql: {sql_text}  sql报错: {result}"}
        # sql执行成功处理
        get_table_success, table_json = get_table_json(table_name=step.table_name,
                                                       task_id=step.task_id)
        # 处理表数据
        if not get_table_success:
            logging.error(f'预览表失败，请重试。 失败原因：{table_json} ,大模型返回: {response_content}')
            return False, {'error': f'预览表失败，请重试。 失败原因：{table_json} ,大模型返回: {response_content}'}
        else:
            table_json = json.dumps(table_json, ensure_ascii=False)
            step.step_sql = sql_text
            step.is_success = True
        # 添加任务表记录
        new_task_table = TaskTable(
            table_name=step.table_name,
            task_id=step.task_id,
            step_id=step.step_id,
            table_preview_json=table_json
        )
        session.add(new_task_table)
        return True, {"table_json": table_json}

    @staticmethod
    def get_step_use_table_columns(session, step):
        table_columns = {}
        task_tables = session.query(TaskTable).join(StepUseTable, TaskTable.table_id == StepUseTable.table_id).filter(
            StepUseTable.step_id == step.step_id).all()
        for task_table in task_tables:
            success, use_table_columns = get_table_columns(task_table.table_name, step.task_id)
            if success:
                table_columns.update({task_table.table_name: use_table_columns.get("columns")})
        return table_columns