from app.models.common.base_models import BaseModel

from db_server.db_init import db as db



class Task(BaseModel):
    __tablename__ = 'tasks'
    task_id = db.Column(db.Integer, primary_key=True)
    task_name = db.Column(db.String(128), nullable=False)
    task_status = db.Column(db.String(32), nullable=True) # 01 待执行 02 执行中
    is_success = db.Column(db.Boolean, nullable=True) # 执行成功

    def to_dict(self, include_extra=None):
        data = {
            'taskId': self.task_id,
            'taskName': self.task_name,
            'taskStatus': self.task_status,
            'isSuccess': self.is_success
        }

        # 添加额外字段
        if include_extra:
            data.update(include_extra)

        return data
