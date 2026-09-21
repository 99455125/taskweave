# 本地图片验证码插件

独立 `ocr` 插件提供 `ocr.recognize`，内嵌本机 CPU OCR 服务，不要求 API Key、GPU 或另开 HTTP 服务；识别时不联网。使用 [ddddocr](https://github.com/sml2h3/ddddocr) 1.6.1 随包模型、ONNX Runtime 1.20.1，OpenCV 固定 4.11.0.86 以使用当前平台预编译包、避免源码构建。固定版本兼顾当前 macOS 13 / Python 3.13；Windows 10 x64 实机与免安装包依赖尚待验证。

## 启动与使用

```bash
uv run --extra gui --extra browser --extra ocr --extra database taskweave workbench
```

开发机首次同步会下载依赖与随包模型；目标离线机由后续打包交付全部资源，不在目标机下载模型。插件管理启用 `ocr`，步骤选择 `playwright` 和 `ocr` 两个插件。配置普通任务/环境变量 loginurl、orgcode、orgsecret。

```python
async def run(ctx, inputs):
    await ctx.call("playwright.page_open", {"url": inputs["loginurl"]})
    await ctx.call("playwright.page_fill", {"selector": {"kind": "label", "value": "机构代码"}, "value": inputs["orgcode"]})
    await ctx.call("playwright.page_fill", {"selector": {"kind": "label", "value": "机构密钥"}, "value": inputs["orgsecret"]})
    image = await ctx.call("playwright.page_element_image", {"selector": inputs["captcha_image_selector"]})
    code = await ctx.call("ocr.recognize", {"image_base64": image["image_base64"], "expected_length": 4})
    await ctx.call("playwright.page_fill", {"selector": inputs["captcha_input_selector"], "value": code["text"]})
    await ctx.call("playwright.page_click", {"selector": {"kind": "role", "value": "button", "name": "登录"}})
    await ctx.call("playwright.page_assert_url", {"url": inputs["authenticated_url_pattern"]})
    return ctx.result(data={"logged_in": True})
```

示例定位器必须按实际采集的页面确定；`authenticated_url_pattern` 为真实登录后地址规则。验证码识别输出 `text`、`engine`、`needs_verification=true`，不返回虚构成功/置信度。可选 `captcha_beta` 变量切换备选模型。API/网页编写均由插件贡献适配规则。

首期仅普通单行图片文字验证码，不实现滑块、点选、算术求解；尺寸/格式、输入大小、空结果和预期长度不符明确报错。不自动刷新或无限重试；识别不准时可修订或人工接管。提交之后必须验证真实登录状态。

同一 worker 内独立单线程初始化和调用模型，显式结束时释放；无 Playwright 依赖，任何图片产生插件均可提供 Base64 图片。模型和 DLL/动态库、第三方许可证需进入便携包，Windows 禁止补装运行库的约束仍由 REQ-007 实机验收。
