# routes_task.py 接口文档

本文档详细描述了 `routes_task.py` 文件中实现的所有API接口。

## 任务管理接口

### 1. 获取任务列表

获取系统中所有任务的列表信息。

**请求URL：** `/tasks`

**请求方式：** GET

**请求参数：** 无

**响应示例：**
```json
{
  "code": 200,
  "data": [
    {
      "taskId": 1,
      "taskName": "示例任务",
      "taskStatus": "01",
      "isSuccess": null
    },
    {
      "taskId": 2,
      "taskName": "另一个任务",
      "taskStatus": "02", // 假设执行中
      "isSuccess": null
    }
  ],
  "message": "success"
}
```

**响应参数说明：**
- `taskId`: (Integer) 任务ID
- `taskName`: (String) 任务名称
- `taskStatus`: (String) 任务状态
    - `01`: 待执行
    - `02`: 执行中
- `isSuccess`: (Boolean/null) 任务执行是否成功
    - `null`: 未执行或执行中
    - `true`: 成功
    - `false`: 失败

### 2. 创建任务

创建一个新的任务。

**请求URL：** `/tasks`

**请求方式：** POST

**请求体 (JSON)：**
```json
{
  "taskName": "新任务的名称"
}
```
**请求参数说明：**
- `taskName`: (String, 必填) 新任务的名称。

**响应示例：**
```json
{
  "code": 200,
  "data": {
    "taskId": 3,
    "taskName": "新任务的名称",
    "taskStatus": "01",
    "isSuccess": null
  },
  "message": "创建任务成功"
}
```
**错误响应示例 (任务名称为空)：**
```json
{
  "code": 500, // 或其他错误码
  "message": "任务名称不能为空"
}
```

### 3. 获取任务详情

获取指定ID任务的详细信息。

**请求URL：** `/tasks/{task_id}`

**请求方式：** GET

**路径参数：**
- `task_id`: (Integer) 要获取详情的任务ID。

**响应示例：**
```json
{
  "code": 200,
  "data": {
    "taskId": 1,
    "taskName": "示例任务",
    "taskStatus": "01",
    "isSuccess": null
  },
  "message": "获取任务详情成功"
}
```
**错误响应示例 (任务不存在)：**
```json
{
  "code": 500, // 或其他错误码
  "message": "任务不存在"
}
```

### 4. 更新任务

更新指定ID任务的名称。

**请求URL：** `/tasks/{task_id}`

**请求方式：** PUT

**路径参数：**
- `task_id`: (Integer) 要更新的任务ID。

**请求体 (JSON)：**
```json
{
  "taskName": "更新后的任务名称"
}
```
**请求参数说明：**
- `taskName`: (String, 必填) 更新后的任务名称。

**响应示例：**
```json
{
  "code": 200,
  "data": {
    "taskId": 1,
    "taskName": "更新后的任务名称",
    "taskStatus": "01", // 假设任务状态未改变
    "isSuccess": null
  },
  "message": "更新任务成功"
}
```
**错误响应示例 (任务不存在)：**
```json
{
  "code": 500,
  "message": "任务不存在"
}
```
**错误响应示例 (任务执行中)：**
```json
{
  "code": 500,
  "message": "任务执行中，无法更新"
}
```
**错误响应示例 (任务名称为空)：**
```json
{
  "code": 500,
  "message": "任务名称不能为空"
}
```

### 5. 删除任务

删除指定的任务及其所有相关数据（包括步骤、文件、表记录和数据库中的物理表）。

**请求URL：** `/tasks/{task_id}`

**请求方式：** DELETE

**路径参数：**
- `task_id`: (Integer) 要删除的任务ID。

**响应示例：**
```json
{
  "code": 200,
  "data": {
    "taskId": 1
  },
  "message": "删除任务成功"
}
```
**错误响应示例 (任务不存在)：**
```json
{
  "code": 500,
  "message": "任务不存在"
}
```
**错误响应示例 (任务执行中)：**
```json
{
  "code": 500,
  "message": "任务执行中，无法删除"
}
```

**说明：**
- 如果任务当前状态为“执行中”（`taskStatus == '02'`），则无法删除。
- 删除操作会级联删除与该任务相关的所有 `Step`, `StepUseTable`, `TaskFile`, `TaskTable` 记录。
- 同时，会尝试删除与该任务关联的物理数据库（通过 `drop_db(task_id)` 实现）。

### 6. 任务操作（执行/解锁）

对指定的任务执行特定操作，如执行任务或解锁任务。

**请求URL：** `/tasks/{task_id}/{action}`

**请求方式：** POST

**路径参数：**
- `task_id`: (Integer) 要操作的任务ID。
- `action`: (String) 要执行的操作类型。
    - `execute`: 执行任务。
    - `unlock`: 解锁任务。

**请求体：** 无

#### 6.1 执行任务 (`action = "execute"`)

**说明：**
- 如果任务当前状态为“执行中”（`taskStatus == '02'`），则无法再次执行。
- 执行任务前会检查该任务是否已添加步骤。
- 执行任务前会检查该任务下的所有步骤（`Step`）是否都已调试成功（`is_success == True` 或者 `step_sql` 不为空）。如果存在未调试成功的步骤，则无法执行。
- 任务执行是异步的，通过线程池 (`thread_pool`) 提交 `TaskService.execute_task` 方法。
- 成功提交执行后，任务状态会更新为“执行中”（`02`），`isSuccess` 会被设置为 `null`。

**响应示例 (开始执行)：**
```json
{
  "code": 200,
  "data": {
    "taskId": 1,
    "taskName": "示例任务",
    "taskStatus": "02",
    "isSuccess": null
  },
  "message": "任务已开始执行"
}
```
**错误响应示例 (任务不存在)：**
```json
{
  "code": 500,
  "message": "任务不存在"
}
```
**错误响应示例 (任务执行中)：**
```json
{
  "code": 500,
  "message": "任务执行中，无法执行"
}
```
**错误响应示例 (没有步骤)：**
```json
{
  "code": 500,
  "message": "任务没有步骤，请先添加步骤"
}
```
**错误响应示例 (存在未调试成功的步骤)：**
```json
{
  "code": 500,
  "message": "存在未调试成功的步骤，请确保所有步骤都调试成功后再执行任务"
}
```

#### 6.2 解锁任务 (`action = "unlock"`)

**说明：**
- 此操作用于将任务状态强制重置为“待执行”（`01`）。
- 主要用于处理任务因异常中断而一直处于“执行中”状态的情况。

**响应示例 (解锁成功)：**
```json
{
  "code": 200,
  "data": {
    "taskId": 1,
    "taskName": "示例任务",
    "taskStatus": "01",
    "isSuccess": null // isSuccess 状态可能保持不变或根据业务逻辑调整
  },
  "message": "任务已解锁"
}
```
**错误响应示例 (任务不存在)：**
```json
{
  "code": 500,
  "message": "任务不存在"
}
```

**错误响应示例 (无效操作)：**
```json
{
  "code": 500, 
  "message": "无效的操作"
}
```

