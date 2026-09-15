# -*- coding: utf-8 -*-
import io
import json
import logging

import pandas as pd
from flask import Blueprint, request
from flask_restful import Resource, Api

from app.models.biz.step_models import Step, StepUseTable
from app.models.biz.task_file_models import TaskFile
from app.models.biz.task_models import Task
from app.models.biz.task_table_models import TaskTable
from app.service.step_service import StepService
from app.service.util.table_tool import TableTool
from app.utils.response_util import success, error
from app.utils.transaciton_tool import route_transactional
from db_server.db_init import db
from tools.db.db_tool import drop_table, get_table_json
from tools.excel.excel_import_tool import import_to_sqlite_by_filestream

task_file_bp = Blueprint('task_file', __name__)
api = Api(task_file_bp)

# 允许的文件扩展名
ALLOWED_EXTENSIONS = {'xlsx', 'xls'}


def allowed_file(filename):
    """检查文件扩展名是否允许"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# 文件列表和文件上传
class TaskFileListResource(Resource):
    # 文件上传
    @route_transactional
    def post(self, task_id):
        """上传Excel文件并关联到任务"""
        try:
            # 检查任务是否存在
            task = Task.query.get(task_id)
            if not task:
                return error("任务不存在")

            # 检查任务状态
            if task.task_status == '02':
                return error("任务执行中，无法上传文件")

            # 检查是否有文件上传
            if 'file' not in request.files:
                return error("没有上传文件")

            file = request.files['file']
            if file.filename == '':
                return error("未选择文件")

            # 验证文件类型
            if not allowed_file(file.filename):
                return error("仅支持xls/xlsx格式的Excel文件")

            # 表名前缀为文件名
            table_name_prefix = file.filename.rsplit('.', 1)[0]
            sheet_columns = {}

            # 读取文件并校验
            try:
                # 读取文件内容到内存
                file_content = file.read()
                file_stream = io.BytesIO(file_content)

                # 从文件中获取所有的sheet
                file_stream.seek(0)
                excel_file = pd.ExcelFile(file_stream)
                sheet_names = excel_file.sheet_names

                # 使用pandas读取Excel内容
                for i in range(len(sheet_names)):
                    table_name = table_name_prefix + '_Sheet' + str(i+1)

                    # 校验任务下是否已存在相同表名
                    table_exists, validation_result = TableTool.validate_task_table_exists(task_id, None,
                                                                                           table_name)
                    if not table_exists:
                        return error(validation_result)

                    # 读取当前工作表以获取其列名
                    df_current_sheet = excel_file.parse(i, nrows=0)
                    columns_current_sheet = df_current_sheet.columns.tolist()
                    sheet_columns.update({str(i): columns_current_sheet})

            except Exception as e:
                logging.error(f"处理Excel文件失败: {str(e)}")
                return error(f"处理Excel文件失败: {str(e)}")

            # 将文件信息保存到数据库
            new_task_file = TaskFile(
                task_id=task_id,
                file_name=file.filename
            )
            db.session.add(new_task_file)
            db.session.flush()  # 获取ID

            # 处理文件
            if not file_stream:
                return error("读取文件异常")

            # 导入文件
            import_sheet_success, import_result = import_sheet_names(task_file=new_task_file,
                                                                     file_stream=file_stream,
                                                                     sheet_names=sheet_names,
                                                                     sheet_columns=sheet_columns,
                                                                     table_name_prefix=table_name_prefix)
            if not import_sheet_success:
                return error(import_result)

            task_tables = TaskTable.query.filter_by(task_file_id=new_task_file.task_file_id).all()

            return success(new_task_file.to_dict(
                include_extra={'taskTables': [task_table.to_dict() for task_table in task_tables]}),
                           "文件上传成功")
        except Exception as e:
            logging.error(f"文件上传失败: {str(e)}")
            return error(f"文件上传失败: {str(e)}")

    # 获取任务的文件列表
    def get(self, task_id):
        """获取任务的文件列表"""
        try:
            # 检查任务是否存在
            task = Task.query.get(task_id)
            if not task:
                return error("任务不存在")

            # 获取所有任务文件
            task_files = TaskFile.query.filter_by(task_id=task_id).all()

            result = []
            for task_file in task_files:
                # 获取关联的表信息
                task_tables = TaskTable.query.filter_by(task_file_id=task_file.task_file_id).all()
                result.append(task_file.to_dict(include_extra={'taskTables':[task_table.to_dict() for task_table in task_tables]}))

            return success(result, "获取文件列表成功")

        except Exception as e:
            logging.error(f"获取文件列表失败: {str(e)}")
            return error(f"获取文件列表失败: {str(e)}")


# 文件详情、更新和删除
class TaskFileResource(Resource):
    def get(self, task_file_id):
        """获取文件详情"""
        try:
            task_file = TaskFile.query.get(task_file_id)
            if not task_file:
                return error("文件不存在")

            # 获取关联的表信息
            task_tables = TaskTable.query.filter_by(task_file_id=task_file.task_file_id).all()

            return success(task_file.to_dict(
                include_extra={'taskTables': [task_table.to_dict() for task_table in task_tables]}),
                           "获取文件详情成功")

        except Exception as e:
            logging.error(f"获取文件详情失败: {str(e)}")
            return error(f"获取文件详情失败: {str(e)}")

    @route_transactional
    def put(self, task_file_id):
        """更新文件（上传新版本）"""
        try:
            task_file = TaskFile.query.get(task_file_id)
            task_id = task_file.task_id
            if not task_file:
                return error("文件不存在")

            # 检查任务状态
            task = Task.query.get(task_id)
            if task.task_status == '02':
                return error("任务执行中，无法更新文件")

            # 检查是否有文件上传
            if 'file' not in request.files:
                return error("没有上传文件")

            file = request.files['file']
            if file.filename == '':
                return error("未选择文件")

            # 验证文件类型
            if not allowed_file(file.filename):
                return error("仅支持xls/xlsx格式的Excel文件")

            # 更新文件名（如果有变化）
            if file.filename != task_file.file_name:
                return error("文件名不允许更新，请重新上传")

            # 取原来的sheets列表
            original_task_tables = TaskTable.query.filter_by(task_file_id=task_file.task_file_id).all()
            original_task_tables_dict = {table.table_name: table for table in original_task_tables}

            # 表名前缀为文件名
            table_name_prefix = file.filename.rsplit('.', 1)[0]
            file_stream = None
            sheet_columns = {}

            # 读取文件并校验
            try:
                # 读取文件内容到内存
                file_content = file.read()
                file_stream = io.BytesIO(file_content)

                # 从文件中获取所有的sheet
                file_stream.seek(0)
                excel_file = pd.ExcelFile(file_stream)
                sheet_names = excel_file.sheet_names

                # 校验sheet名是否重复
                if len(sheet_names) != len(set(sheet_names)):
                    return error("Excel文件中存在重复的工作表名称，请修改后重新上传")

                # 使用pandas读取Excel内容
                for i in range(len(sheet_names)):
                    table_name = table_name_prefix + '_Sheet' + str(i+1)

                    original_task_table = original_task_tables_dict.get(table_name)

                    # 读取当前工作表以获取其列名
                    df_current_sheet = excel_file.parse(i, nrows=0)
                    columns_current_sheet = df_current_sheet.columns.tolist()

                    # 如果原来的表存在，比较sheet
                    if original_task_table:
                        original_sheet_column = json.loads(original_task_table.table_column)
                        all_original_columns_present = set(original_sheet_column).issubset(set(columns_current_sheet))
                        if not all_original_columns_present:
                            return error(f"工作表 {sheet_names[i]} 的列名与原始文件不匹配，请检查后重新上传")

                    # 新增表名
                    if not original_task_table:
                        # 校验任务下是否已存在相同表名
                        table_exists, validation_result = TableTool.validate_task_table_exists(task_id, None,
                                                                                               table_name)
                        if not table_exists:
                            return error(validation_result)

                    sheet_columns.update({str(i): columns_current_sheet})

                # 处理文件
                if not file_stream:
                    return error("读取文件异常")

                # 清理原文件表和数据
                for original_table in original_task_tables:
                    # 删除原有表
                    drop_table(task_id=task_id, table_name=original_table.table_name)

                # 导入文件
                import_sheet_success, import_result = import_sheet_names(task_file=task_file,
                                                                 file_stream=file_stream,
                                                                 sheet_names=sheet_names,
                                                                 sheet_columns=sheet_columns,
                                                                 table_name_prefix=table_name_prefix)
                if not import_sheet_success:
                    return error(import_result)

                task_tables = TaskTable.query.filter_by(task_file_id=task_file.task_file_id).all()

                return success(task_file.to_dict(
                    include_extra={'taskTables': [task_table.to_dict() for task_table in task_tables]}),
                    "文件更新成功")
            except Exception as e:
                logging.error(f"处理Excel文件失败: {str(e)}")
                return error(f"处理Excel文件失败: {str(e)}")

        except Exception as e:
            logging.error(f"更新文件失败: {str(e)}")
            return error(f"更新文件失败: {str(e)}")

    @route_transactional
    def delete(self, task_file_id):
        """删除文件"""
        try:
            task_file = TaskFile.query.get(task_file_id)
            if not task_file:
                return error("文件不存在")

            # 检查任务状态
            task = Task.query.get(task_file.task_id)
            if task.task_status == '02':
                return error("任务执行中，无法删除文件")

            # 获取关联的表信息
            task_tables = TaskTable.query.filter_by(task_file_id=task_file_id).all()
            table_ids = [task_table.table_id for task_table in task_tables]

            # 查询所有关联表中step_order最小的
            min_step = (db.session.query(Step).join(StepUseTable, Step.step_id == StepUseTable.step_id)
                        .filter(StepUseTable.table_id.in_(table_ids)).order_by(Step.step_order.asc()).first())
            # 清理相关step
            if min_step:
                steps = Step.query.filter_by(task_id=task.task_id).filter(Step.step_order >= min_step.step_order).order_by(Step.step_order.asc()).all()
                for step in steps:
                    # 清理步骤关联资源
                    StepService.clear_step(step_id=step.step_id)
                    # 删除步骤关联的表
                    StepUseTable.query.filter_by(step_id=step.step_id).delete()

            for task_table in task_tables:
                # 删除表记录
                db.session.delete(task_table)
                # 删除数据库表
                drop_table(task_id=task_file.task_id, table_name=task_table.table_name)

            # 删除文件记录
            db.session.delete(task_file)

            return success({
                'taskFileId': task_file_id,
                'taskId': task_file.task_id
            }, "文件删除成功")

        except Exception as e:
            logging.error(f"删除文件失败: {str(e)}")
            return error(f"删除文件失败: {str(e)}")


def import_sheet_names(task_file, file_stream, sheet_names, sheet_columns, table_name_prefix):
    for i in range(len(sheet_names)):
        table_name = table_name_prefix + '_Sheet' + str(i+1)

        # 导入文件
        file_stream.seek(0)
        import_success, result = import_to_sqlite_by_filestream(file_stream=file_stream,
                                       table_name=table_name,
                                       task_id=task_file.task_id,
                                       sheet_name=i)

        if not import_success:
            return False, f"导入工作表 {sheet_names[i]} 失败: {result}"

        # sheet_column_json
        sheet_column = sheet_columns.get(str(i))
        sheet_column_json = json.dumps(sheet_column, ensure_ascii=False)

        # table_preview_json
        get_table_success, table_json = get_table_json(table_name=table_name,
                                                       task_id=task_file.task_id)

        if not get_table_success:
            return False, f"获取表 {table_name} 的预览数据失败"

        table_json = json.dumps(table_json, ensure_ascii=False)

        # 如果表已存在，更新。否则，删除
        task_table = TaskTable.query.filter_by(task_file_id=task_file.task_file_id, table_name=table_name).first()
        if task_table:
            task_table.table_column = sheet_column_json
            task_table.table_preview_json = table_json
        else:
            # 添加任务表记录
            new_task_table = TaskTable(
                table_name=table_name,
                task_id=task_file.task_id,
                task_file_id=task_file.task_file_id,
                table_column=sheet_column_json,
                table_preview_json=table_json
            )
            db.session.add(new_task_table)

    return True, None

# 注册API路由
api.add_resource(TaskFileListResource, '/tasks/<int:task_id>/files')
api.add_resource(TaskFileResource, '/task-files/<int:task_file_id>')