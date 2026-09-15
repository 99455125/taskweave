# routes_step.py 接口文档

本文档详细描述了 `routes_step.py` 文件中实现的所有API接口。

## 步骤管理接口

### 1. 获取任务下的步骤列表

获取指定任务下的所有步骤，并按步骤顺序升序排列。

**请求URL：** `/tasks/{task_id}/steps`

**请求方式：** GET

**路径参数：**
- `task_id`: (Integer) 任务ID。

**响应示例：**
```json
{
  "code": 200,
  "data": [
    {
      "stepId": 1,
      "taskId": 1,
      "stepOrder": 1,
      "stepName": "步骤一",
      "stepContent": "步骤一的内容",
      "tableName": "result_table_step1",
      "isSuccess": true,
      "stepSql": "SELECT * FROM table1"
    },
    {
      "stepId": 2,
      "taskId": 1,
      "stepOrder": 2,
      "stepName": "步骤二",
      "stepContent": "步骤二的内容",
      "tableName": "result_table_step2",
      "isSuccess": null,
      "stepSql": null
    }
  ],
  "message": "success"
}
```

**响应参数说明：**
- `stepId`: (Integer) 步骤ID。
- `taskId`: (Integer) 所属任务ID。
- `stepOrder`: (Integer) 步骤在任务中的顺序。
- `stepName`: (String) 步骤名称。
- `stepContent`: (String) 步骤的详细内容或描述。
- `tableName`: (String) 此步骤执行后生成的结果表的名称。
- `isSuccess`: (Boolean/null) 步骤是否执行成功。
    - `true`: 已成功执行。
    - `false`: 执行失败。
    - `null`: 未执行或执行状态未知。
- `stepSql`: (String/null) 大模型返回的SQL语句。

**错误响应示例 (任务不存在)：**
```json
{
  "code": 500, // 或其他错误码
  "message": "任务不存在"
}
```

### 2. 创建新步骤

在指定任务下创建一个新的步骤。

**请求URL：** `/tasks/{task_id}/steps`

**请求方式：** POST

**路径参数：**
- `task_id`: (Integer) 任务ID。

**请求体 (JSON)：**
```json
{
  "stepName": "新的步骤名称",
  "stepContent": "步骤的具体内容或描述",
  "tableName": "步骤生成的结果表名",
  "tables": [1, 2] // 使用的输入表ID列表 (TaskTable ID)
}
```

**请求参数说明：**
- `stepName`: (String, 必填) 步骤的名称。
- `stepContent`: (String, 必填) 步骤的内容或描述。
- `tableName`: (String, 必填) 此步骤执行后生成的结果表的名称。
- `tables`: (Array of Integers, 可选) 此步骤执行时需要用到的输入表的ID列表 (关联 `TaskTable` 表的 `table_id`)。

**响应示例：**
```json
{
  "code": 200,
  "data": {
    "stepId": 3,
    "taskId": 1,
    "stepOrder": 3,
    "stepName": "新的步骤名称",
    "stepContent": "步骤的具体内容或描述",
    "tableName": "步骤生成的结果表名",
    "isSuccess": null,
    "stepSql": null,
    "tables": [1, 2]
  },
  "message": "创建步骤成功"
}
```

**说明：**
- 如果任务状态为“执行中”（`task_status == '02'`），则无法新增步骤。
- 如果任务中存在未调试成功的步骤，则无法新增步骤。
- 新增步骤的 `stepOrder` 会自动设置为当前任务中最大 `stepOrder` + 1。
- `tableName` 在同一任务下必须唯一。
- `isSuccess` 和 `stepSql` 初始为 `null`。

**错误响应示例：**
```json
{
  "code": 500, // 或其他错误码
  "message": "任务执行中，无法新增步骤"
}
```
```json
{
  "code": 500, // 或其他错误码
  "message": "存在未调试成功的步骤，请确保所有步骤都调试成功后再新增步骤"
}
```
```json
{
  "code": 500, // 或其他错误码
  "message": "步骤名称不能为空" // 或其他字段校验错误
}
```
```json
{
  "code": 500, // 或其他错误码
  "message": "任务下已存在相同的表名: [tableName]"
}
```

### 3. 获取步骤详情

获取指定ID步骤的详细信息，包括其使用的输入表ID列表。

**请求URL：** `/steps/{step_id}`

**请求方式：** GET

**路径参数：**
- `step_id`: (Integer) 步骤ID。

**响应示例：**
```json
{
  "code": 200,
  "data": {
    "stepId": 1,
    "taskId": 1,
    "stepOrder": 1,
    "stepName": "步骤一",
    "stepContent": "这是步骤一的内容",
    "tableName": "result_step1",
    "isSuccess": true,
    "stepSql": "SELECT * FROM table1",
    "tables": [10, 12] // 使用的输入表ID列表
  },
  "message": "获取步骤详情成功"
}
```

**错误响应示例 (步骤不存在)：**
```json
{
  "code": 500, // 或其他错误码
  "message": "步骤不存在"
}
```

### 4. 修改指定步骤

修改指定ID步骤的信息。

**请求URL：** `/steps/{step_id}`

**请求方式：** PUT

**路径参数：**
- `step_id`: (Integer) 步骤ID。

**请求体 (JSON)：**
```json
{
  "stepName": "修改后的步骤名称",
  "stepContent": "修改后的步骤内容",
  "tableName": "修改后的结果表名",
  "tables": [1, 3] // 修改后使用的输入表ID列表
}
```

**请求参数说明：**
- `stepName`: (String, 必填) 步骤的名称。
- `stepContent`: (String, 必填) 步骤的内容或描述。
- `tableName`: (String, 必填) 此步骤执行后生成的结果表的名称。
- `tables`: (Array of Integers, 可选) 此步骤执行时需要用到的输入表的ID列表。

**响应示例：**
```json
{
  "code": 200,
  "data": {
    "stepId": 1,
    "taskId": 1,
    "stepOrder": 1,
    "stepName": "修改后的步骤名称",
    "stepContent": "修改后的步骤内容",
    "tableName": "修改后的结果表名",
    "isSuccess": null, // 修改后isSuccess会重置为null
    "stepSql": null,   // 修改后stepSql会重置为null
    "tables": [1, 3]
  },
  "message": "修改步骤成功"
}
```

**说明：**
- 如果任务状态为“执行中”（`task_status == '02'`），则无法修改步骤。
- 只能修改任务中的最后一个步骤，或者第一个未执行成功的步骤。
- 修改步骤后，其 `isSuccess` 状态和 `stepSql` 会重置为 `null`。
- 原有的 `StepUseTable` 关联会先被删除，然后根据请求中的 `tables` 重新创建。
- 如果该步骤之前已生成过结果表 (`TaskTable`)，该物理表会被删除，`TaskTable` 记录也会被删除。
- `tableName` 在同一任务下必须唯一（排除当前步骤自身）。

**错误响应示例：**
```json
{
  "code": 500, // 或其他错误码
  "message": "任务执行中，无法修改步骤"
}
```
```json
{
  "code": 500, // 或其他错误码
  "message": "存在未调试成功的步骤，只能修改第一个未调试成功的步骤"
}
```
```json
{
  "code": 500, // 或其他错误码
  "message": "只能修改最后一个步骤或第一个未调试成功的步骤"
}
```
```json
{
  "code": 500, // 或其他错误码
  "message": "任务下已存在相同的表名: [tableName]"
}
```

### 5. 删除指定步骤

删除指定ID的步骤。

**请求URL：** `/steps/{step_id}`

**请求方式：** DELETE

**路径参数：**
- `step_id`: (Integer) 步骤ID。

**响应示例：**
```json
{
  "code": 200,
  "data": {
    "stepId": 1
  },
  "message": "删除步骤成功"
}
```

**说明：**
- 如果任务状态为“执行中”（`task_status == '02'`），则无法删除步骤。
- 只能删除任务中的最后一个步骤。
- 删除步骤时，会同时删除其在 `StepUseTable` 中的关联记录。
- 如果该步骤已生成过结果表 (`TaskTable`)，该物理表会被删除，`TaskTable` 记录也会被删除。

**错误响应示例：**
```json
{
  "code": 500, // 或其他错误码
  "message": "任务执行中，无法删除步骤"
}
```
```json
{
  "code": 500, // 或其他错误码
  "message": "只能删除最后一个步骤"
}
```

### 6. 执行指定步骤（调试）

执行（调试）指定的步骤。

**请求URL：** `/steps/{step_id}/execute`

**请求方式：** POST

**路径参数：**
- `step_id`: (Integer) 步骤ID。

**请求体：** 无

**响应示例 (成功)：**
```json
{
  "code": 200,
  "data": {
    "stepId": 1,
    "taskId": 1,
    "tableName": "result_step1",
    "tablePreviewJson": "{\"columns\": [\"业务员名称\", \"业务员代码\", \"所属地区\"], \"data\": [{\"业务员名称\": \"王丽\", \"业务员代码\": \"G01\", \"所属地区\": \"上海\"}, {\"业务员名称\": \"王二丽\", \"业务员代码\": \"G02\", \"所属地区\": \"上海\"}, {\"业务员名称\": \"王三丽\", \"业务员代码\": \"G03\", \"所属地区\": \"北京\"}, {\"业务员名称\": \"王四丽\", \"业务员代码\": \"G04\", \"所属地区\": \"北京\"}]}"
  },
  "message": "success" // 或者更具体的成功消息
}
```

**响应示例 (失败)：**
```json
{
  "code": 500, // 或其他错误码
  "message": "执行步骤失败: [具体错误信息]"
}
```

**说明：**
- 如果任务状态为“执行中”（`task_status == '02'`），则无法单独执行步骤。
- 步骤必须关联至少一个可操作表（`StepUseTable` 记录存在）。
- 调试规则：
    - 如果存在未调试成功的步骤，只能调试第一个未调试成功的步骤。
    - 如果所有步骤都已调试成功，只能调试最后一个步骤。
- 执行前会清理当前步骤的数据（`StepService.clear_step`）。
- 任务状态会在步骤执行期间临时设置为 '02' (执行中)，执行完毕后恢复为 '01' (待执行)。
- 如果步骤执行成功，`isSuccess` 会更新为 `true`，并可能生成 `stepSql` 和结果表。
- 响应中的 `tablePreviewJson` 包含执行成功后生成表的预览数据。

**错误响应示例：**
```json
{
  "code": 500, // 或其他错误码
  "message": "步骤不存在"
}
```
```json
{
  "code": 500, // 或其他错误码
  "message": "任务执行中，无法单独执行步骤"
}
```
```json
{
  "code": 500, // 或其他错误码
  "message": "步骤未关联任何表，无法执行，请先勾选可操作表"
}
```
```json
{
  "code": 500, // 或其他错误码
  "message": "存在未调试成功的步骤，只能调试第一个未调试成功的步骤"
}
```
```json
{
  "code": 500, // 或其他错误码
  "message": "只能调试最后一个步骤或第一个未调试成功的步骤"
}
```
```json
{
  "code": 500, // 或其他错误码
  "message": "执行步骤失败: [具体AI服务或SQL执行错误信息]"
}
```
