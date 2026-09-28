# R11 负责人最终验收（2026-09-27）

本轮五项用户调整完成。Sol 分别审查布局与确认逻辑；唯一 P2（切页后旧保存错误污染新页面）已修复并限定复验关闭。负责人独立查看代码、真实操作临时工作区、读取实际持久化状态和逐张复核四宽截图后，将 4 个产品文件、4 个测试文件和4个模块文档整合主树。未提交；用户数据及原混合工作树保留。

## 结果

- 工作台上排最近任务/最近结果，下排快速开始/活跃执行；1440、1280、1024、768 CSS 像素截图包含真实非空执行中实例，窄屏顺序正确。
- 规划采集环境位于能力与素材顶部、插件选择前；负责人真实切换保存并核对 SQLite。隔离采集插件实际收到 environment-B-received，预览截图已亲自核对。AI 栏重复记录入口删除，主生成记录页签仍可使用。
- 确认全部先保存并校验全部，无效项显示步骤名称与原因、不开始确认。全部有效后按 expected_hash 真正确认；负责人点击3个有效步骤，成功提示和勾选出现，数据库3项 VALIDATED 且 verified_hash 匹配；2个无效步骤仍 DRAFT。重新进入保持勾选。确认中途失败保留真实已确认数。
- 负责人定位了重绘销毁菜单槽造成反馈消失的问题，指导使用稳定 client.layout 对话框及 client 通知上下文，保留严格身份与单次重绘代次守卫。保存失败后身份已变化时不污染新页。
- 执行仅有详情/历史两页签。负责人真实打开每步结果，JSON 结果可见；四宽反复切换时右栏、摘要、进度轨道尺寸保持稳定。

## 验证与版本

主树整合后实际运行：

```text
uv run python -m unittest tests.ui.test_step_list tests.ui.test_planning_editor_late_candidate tests.ui.test_execution_details tests.ui.test_workbench_home -v
24 tests passed，1.404s
```

Sol 布局固定快照8项定向通过；确认专项6项通过；后续当前页/迟到保存失败对照2项及7场景独立交错探针通过。测试中的孤立草稿字典不是草稿证据，已移除；本轮不声称重跑所有草稿端到端路径，R10保护由原实现及受影响定向测试维护。

产品源码与已审核快照、浏览器清单绑定一致。证据位于仓库 `output/playwright/r11-root-acceptance/`：`integration.json`保存12文件整合前后SHA256，`before-integration/`保留原文件；`candidate-manifest.json`及`candidate-evidence/`保留浏览器清单、截图、环境标记、结果JSON及脚本；`interaction-notes.md`和`stable-slot-confirm-db.json`为负责人独立操作记录。审核详见[审核记录](ui-redesign-review.md)。

## 边界

仅使用隔离临时数据、本地可控插件；未调用真实外部模型或业务系统，未改用户数据。未运行全量或拼组全量测试，未验证 Windows 离线发布。旧已知测试问题仍见[当前状态](../status.md)。应用需要重启加载新的 Python 页面代码；本轮未擅自重启用户应用。
