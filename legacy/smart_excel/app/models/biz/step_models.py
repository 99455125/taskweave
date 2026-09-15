from app.models.common.base_models import BaseModel
from db_server.db_init import db as db


class Step(BaseModel):
    __tablename__ = 'steps'
    step_id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, nullable=False)
    step_order = db.Column(db.Integer, nullable=False)  # 步骤顺序
    step_name = db.Column(db.String(128), nullable=False)
    step_content = db.Column(db.Text, nullable=False)
    table_name = db.Column(db.String(128), nullable=True)  # 步骤对应的表名
    step_sql = db.Column(db.Text, nullable=True)  # 大模型返回的sql
    is_success = db.Column(db.Boolean, nullable=True)

    def to_dict(self, include_extra=None):
        data = {
            'stepId': self.step_id,
            'taskId': self.task_id,
            'stepOrder': self.step_order,
            'stepName': self.step_name,
            'stepContent': self.step_content,
            'tableName': self.table_name,
            'isSuccess': self.is_success,
            'stepSql': self.step_sql
        }

        # 添加额外字段
        if include_extra:
            data.update(include_extra)

        return data


class StepUseTable(BaseModel):
    __tablename__ = 'step_use_tables'
    step_use_table_id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, nullable=False)  # 任务ID
    step_id = db.Column(db.Integer, nullable=False)  # 步骤ID
    table_id = db.Column(db.Integer, nullable=False)