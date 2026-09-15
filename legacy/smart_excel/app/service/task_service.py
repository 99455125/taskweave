# -*- coding: utf-8 -*-
import logging

from app.models.biz.step_models import Step, StepUseTable
from app.models.biz.task_models import Task
from app.models.biz.task_table_models import TaskTable
from app.service.step_service import StepService
from app.utils.thread_pool import local_storage, Session
from tools.db.db_tool import drop_table


class TaskService:
    @staticmethod
    def execute_task(task_id):
        try:
            # 为每个线程创建新的会话
            local_storage.session = Session()
            session = local_storage.session
            
            # 获取任务执行记录
            task = session.query(Task).get(task_id)
            if not task:
                logging.error(f"任务执行记录不存在，任务ID: {task_id}")
                return

            is_all_success = True
            steps = session.query(Step).filter_by(task_id=task_id).order_by(Step.step_order.asc()).all()

            for step in steps:
                local_storage.current_step = step
                step.is_success = None
                # 检查步骤是否已成功执行
                if not step.step_sql:
                    is_all_success = False
                    logging.error(f"步骤未成功执行，步骤ID: {step.step_id}, 任务ID: {task_id}")
                    break

                # 清理步骤资源
                task_table = session.query(TaskTable).filter_by(step_id=step.step_id).first()

                if not task_table or step.table_name != task_table.table_name:
                    # 如果步骤表名与任务表名不一致，删除旧的表
                    drop_table(table_name=step.table_name, task_id=task_id)

                if task_table:
                    drop_table(table_name=task_table.table_name,
                               task_id=task_table.task_id)

            for step in steps:
                local_storage.current_step = step

                step_success, result = StepService.execute_step(step_id=step.step_id)
                logging.info(f"步骤执行结果: {step_success} {result}, 步骤ID: {step.step_id}, 任务ID: {task_id}")
                if not step_success:
                    is_all_success = False
                    logging.error(f"步骤执行失败，步骤ID: {step.step_id}, 错误信息: {result.get('error', '未知错误')}")
                    break

            task.is_success = is_all_success

        except Exception as e:
            logging.error(f"执行任务逻辑异常: {str(e)}")
            if hasattr(local_storage, 'session') and local_storage.session:
                task = local_storage.session.query(Task).get(task_id)
                task.is_success = False
        finally:
            TaskService.clear_after_step(task_id)
            TaskService.commit_and_close(task_id)

    @staticmethod
    def commit_and_close(task_id):
        # 在finally中重新查询任务执行对象，而不是使用可能已过期的全局变量
        try:
            if hasattr(local_storage, 'session') and local_storage.session:
                # 解锁任务
                task = local_storage.session.query(Task).get(task_id)
                if task:
                    task.task_status = '01'
                local_storage.session.commit()
        except Exception as e:
            logging.error(f"更新任务执行状态失败: {str(e)}")
        finally:
            # 确保会话被关闭
            if hasattr(local_storage, 'session'):
                local_storage.session.close()

    @staticmethod
    def clear_after_step(task_id):
        # 在finally中重新查询任务执行对象，而不是使用可能已过期的全局变量
        try:
            if hasattr(local_storage, 'session') and local_storage.session:
                # 清理后续step
                if local_storage.current_step and local_storage.current_step.is_success is not True:
                    # 删除当前步骤之后的所有步骤
                    steps = (local_storage.session.query(Step).filter_by(task_id=task_id)
                             .filter(Step.step_order >= local_storage.current_step.step_order).order_by(
                        Step.step_order.asc()).all())
                    for step in steps:
                        # 清理步骤资源
                        StepService.clear_step(step_id=step.step_id)
                        local_storage.session.query(StepUseTable).filter_by(step_id=step.step_id).delete()
        except Exception as e:
            logging.error(f"更新任务执行状态失败: {str(e)}")


