from app.models.common.base_models import BaseModel
from db_server.db_init import db as db

# 任务文件表 任务下加挂的文件
class TaskFile(BaseModel):
    __tablename__ = 'task_files'
    task_file_id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, nullable=False, index=True)
    file_name = db.Column(db.String(255), nullable=False)

    def to_dict(self, include_extra=None):
        data = {
            'taskFileId': self.task_file_id,
            'taskId': self.task_id,
            'fileName': self.file_name
        }

        # 添加额外字段
        if include_extra:
            data.update(include_extra)

        return data