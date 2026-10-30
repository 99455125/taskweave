# 本地浏览器演示

此目录保留原有示例路径，browser_demo.py启动本地模拟页面并使用浏览器插件执行，不调用模型。

```bash
uv run --extra browser python examples/req004/browser_demo.py
```

--headed显示浏览器窗口。需要匹配Chromium；输出记录号及本地结果。当前能力与配置见[Playwright插件](../../plugins/playwright/README.md)，SDK见[插件契约](../../docs/contracts/plugins.md)。本例不是真实外部业务系统验收。
