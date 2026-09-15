tools = [
    {
        "name": "import_to_sqlite",
        "description": "使用该工具将excel导入agent的sqlite数据库",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "excel文件路径",
                },
                "table_name": {
                    "type": "string",
                    "description": "sqlite数据库中的表名",
                },
            },
            "required": ["file_path", "table_name"]
        },
    },
    {
        "name": "execute_sql",
        "description": "使用该工具将在agent的sqlite数据库执行任意dml或ddl语句",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "sqlite数据库中的sql语句,可以是任意的dml或ddl语句: create, drop, insert, update, delete, select, PRAGMA table_info() 等",
                },
            },
            "required": ["sql"]
        },
    },
]

tool_names = ", ".join([tool["name"] for tool in tools])