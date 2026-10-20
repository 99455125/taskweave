# 五步骤数据库演示

此目录保留原有示例路径，演示任务/步骤和本地数据库结果，不作为需求规格或完整API清单。

```bash
uv run taskweave --home .runtime/database-demo demo
```

create-task.json是请求示例，api_walkthrough.py通过本地HTTP创建、调试和执行。当前协议见[操作契约](../../docs/contracts/operations.md)，运行入口见[运行指南](../../docs/deployment.md)。演示使用临时工作空间，不能指向需保持只读的用户数据。
