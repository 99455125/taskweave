# -*- coding: utf-8 -*-
import logging
import threading

from flask import Blueprint, request
from flask_restful import Resource, Api

from app.models.biz.step_models import Step, StepUseTable
from app.models.biz.task_models import Task
from app.models.biz.task_table_models import TaskTable
from app.service.step_service import StepService
from app.service.util.table_tool import TableTool
from app.utils.response_util import success, error
from app.utils.transaciton_tool import route_transactional
from db_server.db_init import db

step_bp = Blueprint('step', __name__)
api = Api(step_bp)

# 用于跟踪正在执行的步骤的锁和字典
step_execution_locks = {}
step_execution_lock_manager = threading.Lock()

# 任务下的步骤列表和新增步骤
class StepListResource(Resource):
    # 步骤列表
    def get(self, task_id):
        """获取任务下的所有步骤列表"""
        try:
            # 检查任务是否存在
            task = Task.query.get(task_id)
            if not task:
                return error("任务不存在")

            steps = Step.query.filter_by(task_id=task_id).order_by(Step.step_order.asc()).all()
            return success([step.to_dict() for step in steps])
        except Exception as e:
            logging.error(f"获取步骤列表失败: {str(e)}")
            return error(f"获取步骤列表失败: {str(e)}")

    @route_transactional
    def post(self, task_id):
        """创建新步骤"""
        try:
            # 检查任务是否存在
            task = Task.query.get(task_id)
            if not task:
                return error("任务不存在")

            if task.task_status == '02':
                return error("任务执行中，无法新增步骤")

            # 检查是否存在未调试成功的步骤
            unsuccessful_steps = Step.query.filter_by(task_id=task_id).filter(Step.is_success.isnot(True)).first()
            if unsuccessful_steps:
                return error("存在未调试成功的步骤，请确保所有步骤都调试成功后再新增步骤")

            data = request.json
            validation_result = validate_step_data(data)  # 验证步骤数据
            if validation_result:
                return validation_result

            # 校验任务下是否已存在相同表名
            table_exists, validation_result = TableTool.validate_task_table_exists(task_id, None,
                                                                                   data.get('tableName'))
            if not table_exists:
                return error(validation_result)

            # 获取当前任务最大的步骤顺序
            max_order = db.session.query(db.func.max(Step.step_order)).filter(Step.task_id == task_id).scalar() or 0
            
            new_step = Step(
                task_id=task_id,
                step_order=max_order + 1,
                step_name=data.get('stepName'),
                step_content=data.get('stepContent'),
                table_name=data.get('tableName'),
                is_success=None
            )

            db.session.add(new_step)
            db.session.flush()  # 提交以获取ID但不commit事务

            # 处理步骤使用的表
            tables = data.get('tables', [])
            for table_id in tables:
                step_use_table = StepUseTable(
                    task_id=task_id,
                    step_id=new_step.step_id,
                    table_id=table_id
                )
                db.session.add(step_use_table)

            task_tables = TaskTable.query.filter(TaskTable.table_id.in_(tables)).all()
            task.is_success = None

            return success(new_step.to_dict(include_extra={'taskTables': [task_table.to_dict() for task_table in task_tables]}), "创建步骤成功")

        except Exception as e:
            logging.error(f"创建步骤失败: {str(e)}")
            return error(f"创建步骤失败: {str(e)}")

# 步骤详情、修改、删除
class StepResource(Resource):
    def get(self, step_id):
        """获取指定步骤详情"""
        try:
            step = Step.query.get(step_id)
            if not step:
                return error("步骤不存在")

            # 获取关联的表ID列表
            tables = [item.table_id for item in StepUseTable.query.filter_by(step_id=step_id).all()]

            task_tables = TaskTable.query.filter(TaskTable.table_id.in_(tables)).all()
            return success(step.to_dict(include_extra={'taskTables': [task_table.to_dict() for task_table in task_tables]}), "获取步骤详情成功")
        except Exception as e:
            logging.error(f"获取步骤详情失败: {str(e)}")
            return error(f"获取步骤详情失败: {str(e)}")

    @route_transactional
    def put(self, step_id):
        """修改指定步骤"""
        try:
            step = Step.query.get(step_id)
            if not step:
                return error("步骤不存在")

            # 检查任务是否在执行中
            task = Task.query.get(step.task_id)
            if task.task_status == '02':
                return error("任务执行中，无法修改步骤")


            data = request.json
            validation_result = validate_step_data(data)  # 验证步骤数据
            if validation_result:
                return validation_result

            # 校验任务下是否已存在相同表名
            table_exists, validation_result = TableTool.validate_task_table_exists(step.task_id, step.step_id,
                                                                                   data.get('tableName'))
            if not table_exists:
                return error(validation_result)

            step.step_name = data.get('stepName')
            step.step_content = data.get('stepContent')
            step.table_name = data.get('tableName')

            # 删除原有关联
            StepUseTable.query.filter_by(step_id=step_id).delete()

            # 处理关联表
            tables = data.get('tables', [])
            if tables:
                # 添加新关联
                for table_id in data['tables']:
                    step_use_table = StepUseTable(
                        task_id=step.task_id,
                        step_id=step_id,
                        table_id=table_id
                    )
                    db.session.add(step_use_table)

            task_tables = TaskTable.query.filter(TaskTable.table_id.in_(tables)).all()

            # 清理后面的step状态
            next_steps = Step.query.filter(Step.task_id == step.task_id, Step.step_order > step.step_order).all()
            for next_step in next_steps:
                StepUseTable.query.filter_by(step_id=next_step.step_id).delete()
                StepService.clear_step(step_id=next_step.step_id)

            # 清理表，状态
            StepService.clear_step(step_id=step.step_id)
            task.is_success = None

            return success(step.to_dict(include_extra={'taskTables': [task_table.to_dict() for task_table in task_tables]}), "修改步骤成功")

        except Exception as e:
            logging.error(f"修改步骤失败: {str(e)}")
            return error(f"修改步骤失败: {str(e)}")

    @route_transactional
    def delete(self, step_id):
        """删除指定步骤"""
        try:
            step = Step.query.get(step_id)
            if not step:
                return error("步骤不存在")

            # 检查任务是否在执行中
            task = Task.query.get(step.task_id)
            if task.task_status == '02':
                return error("任务执行中，无法删除步骤")

            # 检查是否为最后一个步骤
            max_order_step = Step.query.filter_by(task_id=step.task_id).order_by(Step.step_order.desc()).first()
            if max_order_step.step_id != step_id:
                return error("只能删除最后一个步骤")

            # 删除步骤关联的表记录
            StepUseTable.query.filter_by(step_id=step_id).delete()

            # 删除原有的步骤下的任务Table表
            StepService.clear_step(step_id=step_id)

            # 删除步骤
            db.session.delete(step)

            return success({'stepId': step_id}, "删除步骤成功")

        except Exception as e:
            logging.error(f"删除步骤失败: {str(e)}")
            return error(f"删除步骤失败: {str(e)}")


# 步骤执行
class StepExecuteResource(Resource):
    @route_transactional
    def post(self, step_id):
        """执行指定步骤"""
        with step_execution_lock_manager:
            if step_id in step_execution_locks:
                return error("该步骤正在执行中，请勿重复提交")
            step_execution_locks[step_id] = True

        try:
            step = Step.query.get(step_id)
            if not step:
                return error("步骤不存在")

            # 检查任务状态
            task = Task.query.get(step.task_id)
            if task.task_status == '02':
                return error("任务执行中，无法单独执行步骤")

            # 检查关联关系
            step_use_tables = StepUseTable.query.filter_by(step_id=step_id).all()
            if not step_use_tables:
                return error("步骤未关联任何表，无法执行，请先勾选可操作表")

            if not step.table_name or not step.step_content:
                return error("步骤表名或内容不能为空")

            # 第一个未执行成功的步骤可以调试
            first_unsuccessful_step = Step.query.filter_by(task_id=step.task_id).filter(
                Step.is_success.isnot(True)).order_by(Step.step_order.asc()).first()
            if first_unsuccessful_step and first_unsuccessful_step.step_id != step_id:
                return error("存在未调试成功的步骤，只能调试第一个未调试成功的步骤")

            # 没有未调试成功的步骤， 只能调试最后一个步骤
            if not first_unsuccessful_step:
                max_order_step = Step.query.filter_by(task_id=step.task_id).order_by(Step.step_order.desc()).first()
                if max_order_step.step_id != step_id:
                    return error("只能调试最后一个步骤或第一个未调试成功的步骤")

            # 清理数据后提交清理状态
            StepService.clear_step(step_id=step_id)
            task.is_success = None
            db.session.commit()

            # 锁定任务
            task.task_status = '02'

            # 执行步骤逻辑
            step_success, result = StepService.execute_step(step_id=step_id)

            #解锁任务
            task.task_status = '01'
            if not step_success:
                return error(f"执行步骤失败: {result.get('error', result)}")

            return success({
                'stepId': step.step_id,
                'taskId': step.task_id,
                'stepSql': step.step_sql,
                'tableName': step.table_name,
                'tablePreviewJson': result.get('table_json', None)
            })
        except Exception as e:
            logging.error(f"执行步骤失败: {str(e)}")
            return error(f"执行步骤失败: {str(e)}")
        finally:
            with step_execution_lock_manager:
                if step_id in step_execution_locks:
                    del step_execution_locks[step_id]

def validate_step_data(data):
    """
    校验步骤数据的必填字段

    Args:
        data: 请求数据

    Returns:
        None 或 错误响应
    """
    if not data:
        return error("请求数据不能为空")

    # 必填字段校验
    required_fields = {
        'stepName': '步骤名称',
        'stepContent': '步骤内容',
        'tableName': '步骤表名'
    }

    for field, field_name in required_fields.items():
        if not data.get(field):
            return error(f"{field_name}不能为空")

    return None


# 注册API路由
api.add_resource(StepListResource, '/tasks/<int:task_id>/steps')
api.add_resource(StepResource, '/steps/<int:step_id>')
api.add_resource(StepExecuteResource, '/steps/<int:step_id>/execute')
