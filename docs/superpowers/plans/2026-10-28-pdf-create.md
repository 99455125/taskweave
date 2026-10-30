# PDF 文本创建实施计划

> **For agentic workers:** 使用 superpowers:executing-plans 在当前会话执行；授权以用户已确认方案为准。

**Goal:** 独立 PDFium 插件创建可离线阅读的中文文本 PDF。
**Architecture:** 独立包通过现有插件 SDK 注册；渲染与文件发布集中在插件内；宿主只增加可选依赖与打包收集。
**Tech Stack:** Python ≥3.10、uv、pypdfium2 5.14.x / PDFium、Noto Sans SC Regular TrueType/OFL、PyInstaller。
**Spec:** [已确认设计](../specs/2026-10-28-pdf-create-design.md)

## Global Constraints

沿用当前混合工作区，保护已有修改；不提交、不推送、不运行全量测试。依赖通过 uv 管理，新增依赖不进入核心默认安装。使用当前 SDK，WRITE、retry_safe=False。

## Review Focus

- 中文字体必须嵌入，缺字不得静默生成方框。
- 长中文与无空格英文不得越界，空行和字面量内容保留。
- 已存在文件及符号链接不得被覆盖；失败不留下目标文件。
- 字体必须随 wheel/冻结包离线可用，保留第三方许可。
- 已有用户插件启用配置必须保留；Windows 实机验证与收集检查区分。

### Task 1: 创建动作与文本排版

**Files:** plugins/pdf/pyproject.toml、src/taskweave_pdf/{__init__,creation}.py、fonts/、tools/prepare_font.py；tests/test_pdf_plugin.py；pyproject.toml、uv.lock。
**Interfaces:** pdf.create(path,text) → {path,page_count,size_bytes}，环境/任务变量 pdf_root。

- [x] 写测试覆盖中文、分页、长英文、字面量、空行、非法字符/路径、已有目标、取消、发布失败清理及真实 worker。
- [x] 运行测试观察未实现失败；增加插件、字体与可选依赖，通过 uv 更新锁定依赖。
- [x] 实现严格输入与缺字校验、按字符宽度换行、分页、临时文件及不覆盖发布；运行 tests.test_pdf_plugin。

### Task 2: 打包、接入与文档

**Files:** packaging/{windows,macos}/taskweave.spec、scripts/build_{windows.ps1,macos.py}、src/taskweave/desktop/bundle.py；tests/test_pdf_packaging.py、test_plugin_architecture.py、test_macos_{bundle,packaging}.py；tests/module-map.json；插件 README 与现有文档。
**Interfaces:** entry point pdf=taskweave_pdf:PdfPlugin；随包字体、OFL 与 PDFium/绑定及依赖许可；现有插件发现及打包清单包含 pdf。

- [x] 先增加发现/收集测试并观察失败，再更新构建、清单及包资源声明。
- [x] 运行 PDF、插件协议/边界、定向打包测试；构建 wheel 检查资源，生成样例并渲染目视检查。
- [x] 同步模块、依赖、分发文档；执行工程检查与 git diff --check；独立审核本次差异并记录平台限制。

## 执行记录

用户已明确要求按确认方案实施，连续执行；不重复请求设计或执行方式审核。测试前提及进展在本文件维护，不使用基于提交的任务脚本（本次未授权 commit）。

2026-10-28 用户改选 pypdfium2，移除 ReportLab。沿用当前计划与设计，不创建第二套任务文档。新增“禁止导入 ReportLab 仍可创建”的回归，切换原生字体与对象生命周期，更新两平台收集；定向测试及冻结/视觉验证继续执行。


## 完成记录（2026-10-28）

- 用户最终要求保留已实现中文字体，继续使用 pypdfium2。
- 运行依赖、uv.lock、两平台打包配置已移除 ReportLab；uv sync --locked --all-extras --group build --group test-pdf 仅卸载本次曾引入的 ReportLab/charset-normalizer，其他已装依赖保持。
- 定向验证：`uv run --locked --extra pdf --group test-pdf --group build python -m unittest tests.test_pdf_plugin tests.test_pdf_packaging tests.test_plugin_architecture tests.test_plugin_contract tests.test_macos_packaging tests.test_macos_bundle -v`，46 项通过。
- 新增回归包括禁止 ReportLab 导入、缺字/路径/防覆盖、真实 worker、并发创建、字体 Unicode 别名/补充平面字符、原生保存失败、发布前后临时文件清理错误、空白 PDF 不嵌入未使用字体。
- 独立审核提出临时文件清理异常覆盖主结果的问题；已先复现再修复。发布成功后通过 cleanup_warning 明确残留路径；发布前保留原错误码与异常链。没有未处理的审核问题。
- 字体子集的补充平面兼容：实际对比保存开关，关闭子集能保留正确 Unicode，开启会变为 U+0000；仅该类文本保留完整字体，生成文件约增加 6 MiB。普通中文继续子集化。
- wheel 构建及字体/度量/OFL/依赖 metadata 检查通过；macOS PyInstaller 独立 smoke 程序已构建，并通过 entry point 离线创建 3 页中文 PDF；三页均经 Poppler 渲染目视检查，文字可读且无截断。
- 工程检查与 git diff --check 通过。未执行全量测试、完整 TaskWeave 发布构建或 Windows EXE 实机测试；现有 Windows 构建脚本/spec 已接入，但目标平台结果仍待 Windows 验证。
