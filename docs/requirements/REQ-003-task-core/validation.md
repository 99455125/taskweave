# REQ-003 验证记录

环境：macOS、Python 3.13、jsonschema 4.26；临时数据库与真实 spawn worker，无真实业务系统。

执行命令：

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/check_req002.py
.venv/bin/python scripts/check_project.py
.venv/bin/python -m taskweave --home .runtime/req003-demo demo
```

集成验证覆盖：五步跨步骤 DB 取值、worker 替换、暂停后重启继续、修改使验证失效、失败停止与显式重试、缺少引用时动作未启动、命令去重、单实例与单运行租约、worker 终止与 UNKNOWN 核对、暂停/取消/超时、上游重跑使下游失效、无数据不创建任务库、结果提交与总库确认之间的故障恢复、自定义表隔离/解析/清理、命名插件结果传递、文件 token 作用域、不同运行隔离、AI 建议不覆盖草稿、READ 工具、WRITE 工具阻止、模型 HTTP 适配、上下文预览、诊断与环境变更校验。

独立 CLI demo 已通过，输出 received_order_id=ORD-1001。独立服务加 HTTP walkthrough 已通过，返回 API-1001。Python wheel 已成功构建，最终安装验证另行记录。

限制：真实模型账号未配置，模型适配仅通过本地 HTTP fixture 验证；Windows 10 x64 实机及 Playwright 尚未验证。自定义表初始创建可用，结构变化明确拒绝并要求迁移，详细插件迁移机制属于 REQ-004。Python 内容是受信任本地代码，不是安全沙箱。

2026-09-17 最终执行：26 项实际集成测试通过（36.499 秒），REQ-002 的 8 项契约检查通过，96 份 Markdown/源码结构检查通过，git diff --check 通过。此前 wheel 构建成功；当前会话虚拟环境缺少 pip，最终 wheel 重建未执行成功，因此不声称最终 wheel 独立安装已验证。

2026-09-18 验证：变量/步骤默认输入合并检查通过；核心 26 项通过（37.288 秒），模型与对话 10 项通过（3.412 秒）。原“拒绝本地密钥保存”检查按用户当前要求更新为允许配置、运行摘要仍脱敏，修正测试中的草稿未确认后通过。验证码 3 项通过（16.135 秒）：禁止 socket 网络连接仍实际识别 1234；浏览器真实采图→本地 OCR→填写→提交→URL/title 断言成功；当前上下文包含验证码图片及密码框定位，不含密码值。连续搜索/失败上下文修复额外回归通过（7.114 秒）。首次本机原生库导入约两分钟，完成初始化后复测通过；Windows 实机与真实业务验证码准确率不在本机 fixture 验收中。


### 分段重跑、人工输入和流程修复验证（2026-09-18）

`tests/test_runtime_inputs.py` 6 项通过（6.149 秒）：任务/步骤缺少必录参数在动作之前暂停、提交输入幂等、同一 worker 继续、独立试跑读取历史成功字段、中间重跑保留前缀结果及 worker 并清理后续结果、不同环境创建执行、修改环境不撤销验证，以及从首步流程试跑后导出本次失败日志。`test_trial_variable_groups.py` 与 `test_task_config_refresh.py` 联合相关核心检查 9 项通过（6.476 秒）；变量与执行回归联合 17 项通过（15.421 秒）。首次分段清理检查发现已删除结果引用仍持有外键，补充清理引用后通过。没有操作用户业务任务或真实登录环境。
