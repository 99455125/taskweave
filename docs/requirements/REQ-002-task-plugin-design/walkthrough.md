# Playwright 契约贯穿示例

可机读示例在 [任务定义](examples/task.json)、[插件能力](examples/playwright.json)、[步骤源码](examples/inspect_page.py)。这是协议示例，不表示插件已实现。

## 1. 内容生成与保存

用户描述“打开指定地址，读取标题，按参数选择截图”。AI 编写服务组合项目 Python 入口约束、Playwright page_open/page_title/page_screenshot 描述及定位/角色规则，输出 inspect_page.py；用户也可直接手写同一文件。

先静态检查，再明确点击试跑。模拟动作返回标题，内容断言标题非空，返回 JSON data；截图开关为 false 时无文件输出。试跑成功后以相同 hash 确认当前 steps 行 VALIDATED。改动 URL 绑定或代码后重新验证，不新增步骤版本。

## 2. 正式执行

协调器解析 task.url/role/capture 参数，登记 run/attempt 并取得租约；worker 用 ctx.call 路由到 Playwright。role=operator 映射到运行内 context，连续步骤复用。ctx.result 的 data 默认由核心持久化到任务库，下游通过输入绑定从库中读取。

截图动作先返回受控 staged_file token，step 返回 handler=playwright.image 的 ResultRequest；handler 保存到当前任务目录，返回文件 ResultRef，总库保存引用。token 不等于任意本机路径，宿主拒绝跨 task/attempt 或 ../ 路径。

另一个 [仅状态示例](examples/open_page.py) 只打开页面返回 ctx.result()：仅写总库状态，不创建任务库。

## 3. 失败场景

- 缺少 url/错误类型：resolve 阶段失败，没有打开页面。
- 未声明调用能力：CAPABILITY_DENIED，执行前/调用时拒绝。
- 标题为空：业务断言失败，不标记 VALIDATED。
- 截图保存失败：RESULT_SAVE_FAILED，保留动作结果，不重新打开/提交业务。
- worker 丢失且已有外部副作用：UNKNOWN；根据 receipt 或插件业务查询核对。
- 手写模式没有 AI 配置：以上静态检查/试跑/保存均不受影响。

## 4. 验证范围

`python scripts/check_req002.py` 使用内存模拟 ctx 运行这两份固定源码，核对调用顺序、参数、结果与失败断言，并在临时 SQLite 验证 DDL/外键/任务隔离。它没有访问真实网站、调用 AI、启动产品 worker 或安装 Playwright。真实测试在 REQ-003/004/007 实施。
