import logging

from tools.db.db_tool import execute_sql
from tools.excel.excel_import_tool import import_to_sqlite

class ToolsHandler:

    @classmethod
    def handler(self, action_tool, action_input, task_id, execution_id):
        logging.info(f"执行内部函数,任务id:{task_id}, 执行id:{execution_id}, tool: {action_tool}, input: {action_input}")
        if 'import_to_sqlite' in action_tool:
            return import_to_sqlite(file_path=action_input['file_path'],
                                    table_name=action_input['table_name'],
                                    task_id=task_id)

        if 'execute_sql' in action_tool:
            return execute_sql(sql=action_input['sql'],
                               task_id=task_id)

        return False, f"无可执行的tool:{action_tool}"
