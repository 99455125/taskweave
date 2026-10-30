# PDF 文本创建插件

独立可选的 pypdfium2 / PDFium 插件，只创建并写入纯文本 PDF。支持中文、自动折行和分页，不修改已有 PDF。

## 安装与使用

```bash
uv sync --locked --extra gui --extra pdf
uv run --extra gui --extra pdf taskweave workbench
```

在插件页启用 `pdf`，在环境或任务变量中配置 `pdf_root` 为允许输出的已有本地目录（任务值覆盖环境值），步骤选择 `pdf.create` 能力。动作输入是输出路径和文本：

```python
async def run(ctx, inputs):
    document = await ctx.call("pdf.create", {
        "path": inputs["pdf_path"],
        "text": inputs["text"],
    })
    return ctx.result(data=document)
```

`path` 来自用户或实际证据，可以是目录内相对路径或绝对路径，后缀须为 `.pdf`。父目录须已存在；不自动建目录，不覆盖已有文件或符号链接。`pdf_root` 是操作范围约束，不能替代操作系统权限隔离。

返回 `{path, page_count, size_bytes}`；成功发布后若临时文件清理失败，额外返回 `cleanup_warning`（含残留路径），PDF 仍已成功创建；发布前的清理失败保留原始错误码并追加清理诊断。其中 path 相对 pdf_root，不是宿主结果附件引用。需要上传文件时可将该目录也配置为 file_root，再用 file.read 的 Base64 读取输出文件；两个插件没有直接调用关系。

## 排版与限制

默认 A4、四边 48pt、12pt 字号、18pt 行距。中文和连续英文按字符实际宽度折行，满页自动分页，保留换行与空行；CRLF/CR 统一为换行，制表符按 4 列展开。文本按字面量写入，不解析 HTML 或 Markdown。空文本创建一页空白 PDF，正文上限 100000 字符。

随插件提供 Noto Sans SC 衍生的静态 Regular 字体，支持常用简繁中文及拉丁字符；字体未覆盖的字符（包括部分 emoji 和罕见汉字）及非法控制字符明确报错，不输出缺字方框。不提供复杂文字塑形、富文本、图片、表格、PDF 读取或已有页面修改。

动作声明 WRITE、retry_safe=False；失败不自动重试。先生成同目录临时文件，完整写入后以不覆盖的硬链接发布。目录须有写权限且文件系统须支持硬链接（例如 NTFS、APFS）；不支持的文件系统明确报错。取消在写入及发布前检查；发布成功后的取消不会回滚文件。正文不默认进入日志。

常见错误以运行时实现为准：PDF_ROOT_REQUIRED、PDF_INPUT_INVALID、PDF_PATH_INVALID、PDF_TARGET_EXISTS、PDF_TEXT_UNSUPPORTED、PDF_FONT_UNAVAILABLE、PDF_RENDER_FAILED、PDF_WRITE_FAILED、CANCELLED。失败不宣称部分成功，不覆盖用户原文件。

## 依赖、许可与打包

运行依赖 pypdfium2 5.14.x（Apache-2.0 / BSD-3-Clause，另含 PDFium 及其依赖许可），仅进入 pdf extra。字体采用 SIL OFL 1.1，版权、许可与来源说明随字体一起打包；fontTools 仅用于重新生成静态字体，不是运行依赖。字体来源、哈希及生成方法见 [字体说明](src/taskweave_pdf/fonts/README.md)。

Windows 构建脚本安装 pdf extra，Windows/macOS PyInstaller spec 收集 taskweave_pdf、字体与字符度量、OFL、pypdfium2、pypdfium2_raw 原生库及包 metadata（含引擎与第三方许可）。目标机不需要 Python、Word、字体安装或网络下载。已有工作空间的插件启用配置保持原样，安装后可在插件页手动启用 pdf。

字体未压缩约 9.9 MiB；插件 wheel 约 6 MiB，不包括 pypdfium2 及原生库，也不代表 EXE 最终增量。普通文本由 PDFium 保存时裁剪未使用的字体字形；当前引擎裁剪会破坏补充平面字符的 Unicode 映射，含这类受支持字符时保留完整字体以确保文本正确，文件会增大约 6 MiB。字符度量与映射随字体生成，运行时不加载 fontTools；所有 PDFium 调用（含资源关闭）在进程内串行执行。Windows EXE 需要在 Windows 构建并实际打开生成 PDF 验收；其他平台的资源收集通过不能替代这一检查。

## 验证

定向测试与映射统一维护在 [测试映射](../../tests/module-map.json) 的 plugins.pdf；测试命令使用 `uv run --locked --extra pdf --group test-pdf --group build python -m unittest tests.test_pdf_plugin tests.test_pdf_packaging -v`。test-pdf 组的 pypdf 仅用于读取生成结果，不进入插件运行依赖。
