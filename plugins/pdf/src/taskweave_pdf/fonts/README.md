# 随包中文字体

TaskWeavePDFSans-Regular.ttf 源于 Google Fonts 的 Noto Sans SC，SIL Open Font License 1.1，许可及版权声明见同目录 OFL.txt。保留原字体全部 Unicode 映射，固定 wght=400，移除 hinting 和排版特性，重命名为 TaskWeave PDF Sans；保留的源字形不意味着支持所有 Unicode 字符。

原始文件：https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf

原始 SHA256：a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da

生成工具：`plugins/pdf/tools/prepare_font.py`（源码仓库内）。在仓库根目录执行：

```bash
uv run --no-project --with fonttools==4.68.0 python plugins/pdf/tools/prepare_font.py /path/to/NotoSansSC-variable.ttf
```

fontTools 仅生成字体资源时使用，不是插件运行依赖。静态字体约 9.9 MiB；普通文本 PDF 由 PDFium 在保存时裁剪未使用字形；含补充平面字符时保留完整字体，避免当前引擎裁剪损坏 Unicode 映射。生成脚本同时输出 .metrics.zlib（字符、字形编号、宽度和字体 SHA256），运行时校验资源一致性并用于折行及 Unicode 映射。发布包包含字体和 OFL，目标机器无需在线下载或安装字体。
