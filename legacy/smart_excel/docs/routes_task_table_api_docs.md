# routes_task_table.py 接口文档

本文档详细描述了 `routes_task_table.py` 文件中实现的所有API接口。这些接口主要用于查询与任务和步骤相关的可用数据表信息，以及下载表数据。

## 任务表管理接口

### 1. 获取指定步骤可用的表列表

获取在特定步骤中可供选择作为输入源的表列表。

**请求URL：** `/steps/{step_id}/available-tables`

**请求方式：** GET

**路径参数：**
- `step_id`: (Integer) 当前步骤的ID。

**查询逻辑说明：**
可用的表包括：
1.  所有通过文件上传直接关联到当前任务的表（即 `task_file_id` 不为空的 `TaskTable` 记录）。
2.  所有由当前任务中、且步骤顺序在当前步骤之前的其他步骤所生成的表（即 `step_id` 对应步骤的 `step_order` 小于当前 `step_id` 对应步骤的 `step_order` 的 `TaskTable` 记录）。

**响应示例：**
```json
{
  "code": 200,
  "data": [
    {
      "tableId": 1,
      "tableName": "uploaded_data_sheet1",
      "taskId": 1,
      "taskFileId": 1,
      "stepId": null,
      "tableColumn": "[\"业务员名称\",\"业务员代码\",\"所属地区\"]",
      "tablePreviewJson": "{\"columns\": [\"业务员名称\", \"业务员代码\", \"所属地区\"], \"data\": [{\"业务员名称\": \"王丽\", \"业务员代码\": \"G01\", \"所属地区\": \"上海\"}, {\"业务员名称\": \"王二丽\", \"业务员代码\": \"G02\", \"所属地区\": \"上海\"}]}"
    },
    {
      "tableId": 2,
      "tableName": "result_from_step1",
      "taskId": 1,
      "taskFileId": null,
      "stepId": 101,
      "tableColumn": "[\"id\",\"resultValue\"]",
      "tablePreviewJson": "{\"columns\": [\"id\", \"resultValue\"], \"data\": [{\"id\": 1, \"resultValue\": \"output\"}]}"
    }
  ],
  "message": "success"
}
```

**响应参数说明 (数组中的每个对象)：**
- `tableId`: (Integer) 表的唯一ID。
- `tableName`: (String) 表的名称。
- `taskId`: (Integer) 表所属的任务ID。
- `taskFileId`: (Integer/null) 如果表是通过文件上传创建的，则为关联的 `TaskFile` ID；否则为 `null`。
- `stepId`: (Integer/null) 如果表是由某个步骤生成的，则为关联的 `Step` ID；否则为 `null`。
- `tableColumn`: (String) 一个包含列名数组的JSON字符串。
- `tablePreviewJson`: (String) 表数据预览，一个JSON字符串，其内容为包含 "columns" 和 "data" 键的JSON对象。

**错误响应示例 (步骤不存在)：**
```json
{
  "code": 500,
  "message": "步骤不存在"
}
```

### 2. 获取指定任务所有可用的表列表

获取指定任务下所有已创建的表，包括通过文件上传创建的表和通过步骤执行生成的表。

**请求URL：** `/tasks/{task_id}/available-tables`

**请求方式：** GET

**路径参数：**
- `task_id`: (Integer) 任务的ID。

**响应示例：**
```json
{
  "code": 200,
  "data": [
    {
      "tableId": 1,
      "tableName": "uploaded_data_sheet1",
      "taskId": 1,
      "taskFileId": 1,
      "stepId": null,
      "tableColumn": "[\"业务员名称\",\"业务员代码\",\"所属地区\"]",
      "tablePreviewJson": "{\"columns\": [\"业务员名称\", \"业务员代码\", \"所属地区\"], \"data\": [{\"业务员名称\": \"王丽\", \"业务员代码\": \"G01\", \"所属地区\": \"上海\"}]}"
    },
    {
      "tableId": 2,
      "tableName": "result_from_step1",
      "taskId": 1,
      "taskFileId": null,
      "stepId": 101,
      "tableColumn": "[\"id\",\"resultValue\"]",
      "tablePreviewJson": "{\"columns\": [\"id\", \"resultValue\"], \"data\": [{\"id\": 1, \"resultValue\": \"output\"}]}"
    },
    {
      "tableId": 3,
      "tableName": "result_from_step2",
      "taskId": 1,
      "taskFileId": null,
      "stepId": 102,
      "tableColumn": "[\"key\",\"final_data\"]",
      "tablePreviewJson": "{\"columns\": [\"key\", \"final_data\"], \"data\": [{\"key\": \"A\", \"final_data\": 100}]}"
    }
  ],
  "message": "success"
}
```

**响应参数说明 (数组中的每个对象)：**
- `tableId`: (Integer) 表的唯一ID。
- `tableName`: (String) 表的名称。
- `taskId`: (Integer) 表所属的任务ID。
- `taskFileId`: (Integer/null) 如果表是通过文件上传创建的，则为关联的 `TaskFile` ID；否则为 `null`。
- `stepId`: (Integer/null) 如果表是由某个步骤生成的，则为关联的 `Step` ID；否则为 `null`。
- `tableColumn`: (String) 一个包含列名数组的JSON字符串。
- `tablePreviewJson`: (String) 表数据预览，一个JSON字符串，其内容为包含 "columns" 和 "data" 键的JSON对象。

**错误响应示例 (任务不存在)：**
```json
{
  "code": 500,
  "message": "任务不存在"
}
```

### 3. 获取指定表的详细信息

获取具有特定ID的 `TaskTable` 记录的详细信息。

**请求URL：** `/tables/{table_id}`

**请求方式：** GET

**路径参数：**
- `table_id`: (Integer) 要获取详情的表的ID。

**响应示例：**
```json
{
  "code": 200,
  "data": {
    "tableId": 1,
    "tableName": "uploaded_data_sheet1",
    "taskId": 1,
    "taskFileId": 1,
    "stepId": null,
    "tableColumn": "[\"业务员名称\",\"业务员代码\",\"所属地区\"]",
    "tablePreviewJson": "{\"columns\": [\"业务员名称\", \"业务员代码\", \"所属地区\"], \"data\": [{\"业务员名称\": \"王丽\", \"业务员代码\": \"G01\", \"所属地区\": \"上海\"}]}"
  },
  "message": "success"
}
```

**响应参数说明：**
- `tableId`: (Integer) 表的唯一ID。
- `tableName`: (String) 表的名称。
- `taskId`: (Integer) 表所属的任务ID。
- `taskFileId`: (Integer/null) 如果表是通过文件上传创建的，则为关联的 `TaskFile` ID；否则为 `null`。
- `stepId`: (Integer/null) 如果表是由某个步骤生成的，则为关联的 `Step` ID；否则为 `null`。
- `tableColumn`: (String) 一个包含列名数组的JSON字符串。
- `tablePreviewJson`: (String) 表数据预览，一个JSON字符串，其内容为包含 "columns" 和 "data" 键的JSON对象。

**错误响应示例 (表不存在)：**
```json
{
  "code": 500,
  "message": "表不存在"
}
```

### 4. 下载任务中的指定表

下载指定任务中特定名称的表。支持导出为 Excel (`.xlsx`) 或 CSV (`.csv`) 格式。

**请求URL：** `/tasks/{task_id}/download/{table_name}/{file_type}`

**请求方式：** GET

**路径参数：**
- `task_id`: (Integer) 任务的ID。
- `table_name`: (String) 要下载的表的名称。
- `file_type`: (String) 导出的文件类型。支持 `xlsx` 和 `csv`。

**查询参数 (可选):**
- `exportFileName`: (String) 如果提供此参数，文件将保存在服务器的指定路径下，而不是通过HTTP响应流式传输给客户端。响应将是JSON格式。

**响应 (流式下载):**

当不提供 `exportFileName` 参数时，API会以文件流的形式返回数据。

*   **如果 `file_type` 是 `xlsx`:**
    *   **状态码：** 200 OK
    *   **Content-Type：** `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
    *   **Content-Disposition：** `attachment; filename="{table_name}.xlsx"`
    *   **Body：** Excel文件的二进制内容。

*   **如果 `file_type` 是 `csv`:**
    *   **状态码：** 200 OK
    *   **Content-Type：** `text/csv`
    *   **Content-Disposition：** `attachment; filename="{table_name}.csv"`
    *   **Body：** CSV文件的二进制内容。

**响应 (保存到服务器):**

当提供 `exportFileName` 参数时，API会返回一个JSON响应。

**响应示例 (保存到服务器成功):**
```json
{
  "code": 200,
  "data": {},
  "message": "文件已成功导出到 [file_path]"
}
```

**说明：**
- 如果任务状态为“执行中”（`task_status == '02'`），则无法下载表数据。
- 请求的 `table_name` 必须在指定的 `task_id` 下存在对应的 `TaskTable` 记录。

**错误响应示例：**
```json
{
  "code": 500, 
  "message": "任务不存在"
}
```
```json
{
  "code": 500,
  "message": "任务执行中，无法下载表数据"
}
```
```json
{
  "code": 500,
  "message": "表名不能为空"
}
```
```json
{
  "code": 500,
  "message": "任务 [task_id] 中不存在名为 [table_name] 的结果表"
}
```
```json
{
  "code": 500,
  "message": "导出表 [table_name] 失败: [具体错误信息]"
}
```
