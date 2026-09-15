from app.models.biz.step_models import Step
from app.models.biz.task_table_models import TaskTable


class TableTool:
    @staticmethod
    def validate_task_table_exists(task_id, step_id, table_name):
        """
        校验任务下是否已存在相同表名

        Args:
            task_id: 任务ID
            step_id: 步骤ID
            table_name: 表名

        Returns:
            None 或 错误响应
        """
        if not table_name:
            return False, "表名不能为空"

        existing_task_table = TaskTable.query.filter_by(
            task_id=task_id,
            table_name=table_name
        ).filter(TaskTable.task_file_id.isnot(None)).first()

        if existing_task_table:
            return False, f"该任务下已存在名为'{table_name}'的文件导入表，请使用其他表名"

        step = Step.query.filter_by(
            task_id=task_id,
            table_name=table_name
        ).filter(
            Step.step_id != step_id
        ).first()

        if step:
            step_name = step.step_name
            return False, f"该任务下名为'{table_name}'的表，已被名为'{step_name}'的步骤使用，请使用其他表名"

        return True, None