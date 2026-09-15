# -*- coding: utf-8 -*-
import logging

from flask import Blueprint, request
from flask_restful import Resource, Api
from sqlalchemy import or_

from app.models.biz.step_models import Step, StepUseTable
from app.models.biz.task_file_models import TaskFile
from app.models.biz.task_models import Task
from app.models.biz.task_table_models import TaskTable
from app.service.task_service import TaskService
from app.utils.response_util import success, error
from app.utils.thread_pool import thread_pool
from app.utils.transaciton_tool import route_transactional
from db_server.db_init import db as db
from tools.db.db_tool import drop_db

task_bp = Blueprint('task', __name__)
api = Api(task_bp)



# 任务列表和创建
class TaskListResource(Resource):
    # 任务列表
    def get(self):
        """获取所有任务列表"""
        try:
            tasks = Task.query.all()
            return success([t.to_dict() for t in tasks])
        except Exception as e:
            return error(f"查询任务列表失败: {str(e)}")

    @route_transactional
    def post(self):
        """创建新任务"""
        try:
            data = request.json
            if not data:
                return error("请求数据不能为空")

            if not data.get('taskName'):
                return error("任务名称不能为空")

            new_task = Task(
                task_name=data.get('taskName'),
                task_status='01',  # 待执行
                is_success=None
            )

            db.session.add(new_task)
            db.session.flush()

            return success(new_task.to_dict(), "创建任务成功")

        except Exception as e:
            return error(f"创建任务失败: {str(e)}")


# 任务详情,更新,删除
class TaskResource(Resource):
    def get(self, task_id):
        """获取指定任务详情"""
        try:
            task = Task.query.get(task_id)
            if not task:
                return error("任务不存在")

            return success(task.to_dict(), "获取任务详情成功")
        except Exception as e:
            return error(f"获取任务详情失败: {str(e)}")

    def put(self, task_id):
        """删除指定任务"""
        try:
            task_obj = Task.query.get(task_id)
            if not task_obj:
                return error("任务不存在")

            if task_obj.task_status == '02':
                return error("任务执行中，无法更新")

            data = request.json
            if not data:
                return error("请求数据不能为空")

            if not data.get('taskName'):
                return error("任务名称不能为空")

            task_obj.task_name = data.get('taskName')

            return success(task_obj.to_dict(), "更新任务成功")

        except Exception as e:
            return error(f"更新任务失败: {str(e)}")


    def delete(self, task_id):
        """删除指定任务"""
        try:
            task_obj = Task.query.get(task_id)
            if not task_obj:
                return error("任务不存在")
                
            if task_obj.task_status == '02':
                return error("任务执行中，无法删除")

            # 删除任务相关表
            Step.query.filter_by(task_id=task_id).delete()
            StepUseTable.query.filter_by(task_id=task_id).delete()
            TaskFile.query.filter_by(task_id=task_id).delete()
            TaskTable.query.filter_by(task_id=task_id).delete()


            # 删除任务本身
            db.session.delete(task_obj)
            db.session.commit()
            logging.info(f"任务删除成功: {task_id}")

            # 清理任务相关的数据库表
            drop_db(task_id)
            logging.info(f"数据库删除成功: {task_id}")
            return success({'taskId': task_id}, "删除任务成功")
        except Exception as e:
            db.session.rollback()
            return error(f"删除任务失败: {str(e)}")


# 任务执行
class TaskExecuteResource(Resource):
    def post(self, task_id, action):
        """执行指定任务的操作"""
        try:
            task_obj = Task.query.get(task_id)
            if not task_obj:
                return error("任务不存在")
                
            if action == 'execute':
                if task_obj.task_status == '02':
                    return error("任务执行中，无法执行")

                if Step.query.filter_by(task_id=task_id).count() == 0:
                    return error("任务没有步骤，请先添加步骤")

                #  所有任务必须调试成功
                if Step.query.filter_by(task_id=task_id).filter(or_(Step.is_success.isnot(True), Step.step_sql.is_(None))).count() > 0:
                    return error("存在未调试成功的步骤，请确保所有步骤都调试成功后再执行任务")

                # 设置任务状态为执行中
                task_obj.is_success = None
                task_obj.task_status = '02'
                Step.query.filter_by(task_id=task_id).update({'is_success': None})

                db.session.commit()

                # 执行任务
                thread_pool.submit(
                    TaskService.execute_task,
                    task_obj.task_id
                )
                return success(task_obj.to_dict(), "任务已开始执行")

            # 任务强制解锁
            elif action == 'unlock':
                task_obj.task_status = '01'  # 设置为待执行状态
                # 解锁成功
                db.session.commit()
                return success(task_obj.to_dict(), "任务已解锁")
                
            else:
                return error("无效的操作")
                
        except Exception as e:
            db.session.rollback()
            logging.error(f"执行任务操作失败: {str(e)}")
            return error(f"执行任务操作失败: {str(e)}")


# 注册api
api.add_resource(TaskListResource, '/tasks')
api.add_resource(TaskResource, '/tasks/<int:task_id>')
api.add_resource(TaskExecuteResource, '/tasks/<int:task_id>/<string:action>')