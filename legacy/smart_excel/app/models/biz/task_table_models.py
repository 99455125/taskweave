from db_server.db_init import db as db

# 资源表， 表示step执行后产生的资源
class TaskTable(db.Model):
    __tablename__ = 'task_tables'
    table_id = db.Column(db.Integer, primary_key=True)
    table_name = db.Column(db.String(128), nullable=False)  # 表名
    task_id = db.Column(db.Integer, nullable=False, index=True)  # 任务ID
    task_file_id = db.Column(db.Integer, nullable=True)  # 任务文件ID
    step_id = db.Column(db.Integer, nullable=True)  # 步骤ID
    table_column = db.Column(db.Text, nullable=True)  # 表格excel sheet列信息
    table_preview_json = db.Column(db.Text, nullable=True)  # 表格JSON

    def to_dict(self, include_extra=None):
        data = {
            'tableId': self.table_id,
            'tableName': self.table_name,
            'taskId': self.task_id,
            'taskFileId': self.task_file_id,
            'stepId': self.step_id,
            'tableColumn': self.table_column,
            'tablePreviewJson': self.table_preview_json
        }

        # 添加额外字段
        if include_extra:
            data.update(include_extra)

        return data