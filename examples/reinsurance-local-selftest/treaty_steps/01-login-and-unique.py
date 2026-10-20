async def run(ctx, inputs):
    # Existing local credentials stay outside portable task packages and outputs.
    credentials = await ctx.call("file.read", {
        "path": inputs["credentials_path"], "format": "json", "max_bytes": 65536
    })
    ui = credentials["content"]["ui"]
    if ui["url"] != "http://localhost:9877/login":
        raise ValueError("凭据仅允许用于交接指定的本地登录地址")
    role = inputs["role"]
    account = ui["accounts"][inputs["account_key"]]
    if account != inputs["expected_account"] or not ui["sharedPassword"]:
        raise ValueError("交接账号或已有密码不完整")
    await ctx.call("playwright.page_open", {"url": ui["url"], "role": role})
    await ctx.call("playwright.page_assert_state", {
        "selector": "#username", "expected": {"count": 1, "visible": True}, "role": role
    })
    # Explicitly choose Chinese; browser locale alone does not change product language.
    await ctx.call("playwright.page_click", {
        "selector": "#root > div:nth-of-type(1) > div:nth-of-type(3) > div:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(1) > form:nth-of-type(1) > div:nth-of-type(4) > div:nth-of-type(1) > div:nth-of-type(1)", "role": role
    })
    await ctx.call("playwright.page_click", {
        "selector": {"kind": "role", "value": "option", "name": "中文", "exact": True}, "role": role
    })
    placeholder = await ctx.call("playwright.page_attribute", {
        "selector": "#username", "name": "placeholder", "role": role
    })
    if placeholder["value"] != "请输入用户名":
        raise ValueError("登录页未完成中文切换")
    await ctx.call("playwright.page_fill", {"selector": "#username", "value": account, "role": role})
    await ctx.call("playwright.page_fill", {"selector": "#password", "value": ui["sharedPassword"], "role": role})
    # Local handoff explicitly disables image verification; never reuse this for UAT.
    await ctx.call("playwright.page_fill", {"selector": "#verifyCode", "value": str(ui["captcha"]), "role": role})
    await ctx.call("playwright.page_click", {
        "selector": {"kind": "role", "value": "button", "name": "登 录", "exact": True}, "role": role
    })
    await ctx.call("playwright.page_assert_state", {
        "selector": "#emailOrTokenVerifyCode", "expected": {"count": 1, "visible": True}, "role": role
    })
    await ctx.call("playwright.page_fill", {
        "selector": "#emailOrTokenVerifyCode", "value": str(ui["emailCode"]), "role": role
    })
    await ctx.call("playwright.page_click", {
        "selector": {"kind": "role", "value": "button", "name": "确 认", "exact": True}, "role": role
    })
    await ctx.call("playwright.page_assert_url", {"url": "http://localhost:9877/Home", "role": role})
    await ctx.call("playwright.page_assert_text", {"selector": "body", "text": "用户名称" + account, "role": role})
    await ctx.call("playwright.page_open", {"url": "http://localhost:9877/TreatyManagement/Treaty", "role": role})
    await ctx.call("playwright.page_assert_state", {"selector": "#查询条件_treatyCode", "expected": {"count": 1, "visible": True}, "role": "cedant"})
    await ctx.call("playwright.page_click", {"selector": "text=全部", "role": "cedant"})
    stamp = await ctx.call("utility.now", {"timezone": inputs["timestamp_timezone"]})
    suffix = inputs["name_prefix"] + stamp["compact"]
    if not suffix.replace("-", "").isalnum():
        raise ValueError("测试编号只接受字母、数字和连字符")
    await ctx.call("playwright.page_fill", {"selector": "#查询条件_treatyCode", "value": suffix, "role": "cedant"})
    await ctx.call("playwright.page_assert_value", {"selector": "#查询条件_treatyCode", "value": suffix, "role": "cedant"})
    await ctx.call("playwright.page_click", {"selector": {"kind": "role", "value": "button", "name": "查 询", "exact": True}, "role": "cedant"})
    await ctx.call("playwright.page_assert_text", {"selector": "main", "text": inputs["empty_result_text"], "role": "cedant"})
    records = await ctx.call("playwright.page_list", {"selector": "main a", "role": "cedant"})
    if records["truncated"]:
        raise ValueError("查重记录超出读取范围")
    duplicate_count = len([row for row in records["items"] if "机构合约编号：" + suffix in row["text"]])
    if duplicate_count != 0:
        raise ValueError("编号已存在，停止新建合约")
    return ctx.result(data={"contract_suffix": suffix, "timestamp": stamp["compact"], "duplicate_count": duplicate_count})
