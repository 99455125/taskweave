async def run(ctx, inputs):
    await ctx.call("playwright.page_open", {"url": "https://ire-uat.shie.com.cn/login", "role": "operator"})
    await ctx.call("playwright.page_assert_url", {"url": "**/login", "role": "operator"})
    await ctx.call("playwright.page_click", {"selector": "#root > div:nth-of-type(1) > div:nth-of-type(3) > div:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(1) > form:nth-of-type(1) > div:nth-of-type(4) > div:nth-of-type(1) > div:nth-of-type(1)", "role": "operator"})
    await ctx.call("playwright.page_click", {"selector": {"kind": "role", "value": "option", "name": "中文", "exact": True}, "role": "operator"})
    await ctx.call("playwright.page_assert_state", {"selector":"#username", "expected":{"count":1,"visible":True}, "role":"operator"})
    username = await ctx.call("playwright.page_attribute", {"selector": "#username", "name": "placeholder", "role": "operator"})
    password = await ctx.call("playwright.page_attribute", {"selector": "#password", "name": "placeholder", "role": "operator"})
    verification = await ctx.call("playwright.page_attribute", {"selector": "#verifyCode", "name": "placeholder", "role": "operator"})
    if username["value"] != "请输入用户名" or password["value"] != "请输入登录密码" or verification["value"] != "请输入验证码":
        raise ValueError("登录页面没有完成显式中文切换")
    await ctx.call("playwright.page_assert_state", {"selector": {"kind": "role", "value": "button", "name": "登 录", "exact": True}, "expected": {"count": 1, "visible": True, "enabled": True}, "role": "operator"})
    return ctx.result(data={"language": "中文"})