# -*- coding: utf-8 -*-
import logging

from flask import Blueprint, request, send_file
from flask_restful import Resource, Api
from sqlalchemy import and_, or_

from app.models.biz.step_models import Step
from app.models.biz.task_models import Task
from app.models.biz.task_table_models import TaskTable
from app.utils.response_util import success, error
from db_server.db_init import db
from tools.excel.excel_export_tool import export_table_to_excel_file_path, export_table_to_csv_stream, \
    export_table_to_excel_stream

task_table_bp = Blueprint('task_table', __name__)
api = Api(task_table_bp)


# 步骤可用表查询
class StepAvailableTablesResource(Resource):
    def get(self, step_id):
        """获取指定步骤可用的表列表

        查询条件:
        1. task_file_id 不为空的表
        2. 或者 step_id 关联的 step 的 orderNo 比当前步骤的 orderNo 小的表
        """
        try:
            # 获取当前步骤信息
            current_step = Step.query.get(step_id)
            if not current_step:
                return error("步骤不存在")

            # 获取当前步骤的 task_id 和 orderNo
            task_id = current_step.task_id

            # 查询 orderNo 小于当前步骤的所有步骤 ID
            previous_step_ids = db.session.query(Step.step_id).filter(
                and_(
                    Step.task_id == task_id,
                    Step.step_order < current_step.step_order
                )
            ).all()
            previous_step_ids = [s_id[0] for s_id in previous_step_ids]

            # 查询可用表
            available_tables = TaskTable.query.filter(
                and_(
                    TaskTable.task_id == task_id,
                    or_(
                        TaskTable.task_file_id.isnot(None),
                        TaskTable.step_id.in_(previous_step_ids) if previous_step_ids else False
                    )
                )
            ).all()

            return success([table.to_dict() for table in available_tables])
        except Exception as e:
            logging.error(f"查询步骤可用表失败: {str(e)}")
            return error(f"查询步骤可用表失败: {str(e)}")

# 步骤可用表查询
class TaskAvailableTablesResource(Resource):
    def get(self, task_id):
        try:
            # 获取当前步骤信息
            task = Task.query.get(task_id)
            if not task:
                return error("任务不存在")

            # 查询可用表
            available_tables = TaskTable.query.filter_by(task_id=task_id).all()

            return success([table.to_dict() for table in available_tables])
        except Exception as e:
            logging.error(f"查询步骤可用表失败: {str(e)}")
            return error(f"查询步骤可用表失败: {str(e)}")

# 任务表详情
class TaskTableResource(Resource):
    def get(self, table_id):
        """获取指定表的详细信息"""
        try:
            table = TaskTable.query.get(table_id)
            if not table:
                return error("表不存在")
            
            return success(table.to_dict())
        except Exception as e:
            return error(f"获取表详情失败: {str(e)}")

def export_table_to_stream(task_id:str, table_name: str, file_type='xlsx'):
    if file_type == 'xlsx' or not file_type:
        return export_table_to_excel_stream(task_id=task_id, table_name=table_name)
    else:
        return export_table_to_csv_stream(task_id=task_id, table_name=table_name)


class TableResource(Resource):
    def get(self, task_id, table_name, file_type):
        try:
            # 获取当前步骤信息
            task = Task.query.get(task_id)
            if not task:
                return error("任务不存在")

            if task.task_status == '02':
                return error("任务执行中，无法下载表数据")

            if not table_name:
                return error("表名不能为空")

            if TaskTable.query.filter_by(task_id=task_id, table_name=table_name).count() == 0:
                return error(f"任务 {task_id} 中不存在名为 {table_name} 的结果表")

            # 从查询参数中获取 exportFileName
            export_file_name = request.args.get("exportFileName")
            if export_file_name:
                logging.info(f"导出表 {table_name} 的数据到 Excel 文件，文件名: {export_file_name}")
                excel_success, result_msg = export_table_to_excel_file_path(task_id=task_id, table_name=table_name, file_path=export_file_name)
                if not excel_success:
                    return error(result_msg)
                return success({}, result_msg)
            else:
                excel_success, result_msg, excel_stream = export_table_to_stream(task_id=task_id, table_name=table_name, file_type=file_type)
                if not excel_success:
                    return error(result_msg)
                logging.info(f"成功生成表 {table_name} 的文件流，准备发送给客户端。")

                if file_type == 'csv':
                    mimetype = 'text/csv'
                    download_name = f'{table_name}.csv'
                else:  # default to xlsx
                    mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                    download_name = f'{table_name}.xlsx'

                return send_file(
                    excel_stream,
                    as_attachment=True,
                    download_name=download_name,
                    mimetype=mimetype
                )

        except Exception as e:
            return error(f"获取任务表列表失败: {str(e)}")

# 注册 API
api.add_resource(StepAvailableTablesResource, '/steps/<int:step_id>/available-tables')
api.add_resource(TaskAvailableTablesResource, '/tasks/<int:task_id>/available-tables')
api.add_resource(TaskTableResource, '/tables/<int:table_id>')
api.add_resource(TableResource, '/tasks/<int:task_id>/download/<string:table_name>/<string:file_type>')
