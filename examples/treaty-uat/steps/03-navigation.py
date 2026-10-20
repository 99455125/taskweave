async def run(ctx, inputs):
    page = await ctx.call("playwright.page_inspect", {"role": "operator"})
    if page["url"] == "https://ire-uat.shie.com.cn/Home":
        await ctx.call("playwright.page_assert_url", {"url": "https://ire-uat.shie.com.cn/Home", "role": "operator"})
        await ctx.call("playwright.page_click", {"selector": {"kind": "role", "value": "menuitem", "name": "合约交易管理", "exact": True}, "role": "operator"})
        await ctx.call("playwright.page_click", {"selector": {"kind": "role", "value": "menuitem", "name": "合约", "exact": True}, "role": "operator"})
    await ctx.call("playwright.page_assert_url", {"url": "https://ire-uat.shie.com.cn/TreatyManagement/Treaty", "role": "operator"})
    await ctx.call("playwright.page_assert_state", {"selector": "#查询条件_treatyCode", "expected": {"count": 1, "visible": True}, "role": "operator"})
    await ctx.call("playwright.page_assert_state", {"selector": {"kind": "role", "value": "tab", "name": "全部", "exact": False}, "expected": {"count": 1, "enabled": True}, "role": "operator"})
    await ctx.call("playwright.page_click", {"selector": {"kind": "role", "value": "tab", "name": "全部", "exact": False}, "role": "operator"})
    stamp = await ctx.call("utility.now", {"timezone": inputs["timestamp_timezone"]})
    suffix = inputs["name_prefix"] + stamp["compact"]
    if not suffix.replace("-", "").isalnum():
        raise ValueError("测试编号只接受字母、数字和连字符")
    await ctx.call("playwright.page_fill", {"selector": "#查询条件_treatyCode", "value": suffix, "role": "operator"})
    await ctx.call("playwright.page_assert_value", {"selector": "#查询条件_treatyCode", "value": suffix, "role": "operator"})
    await ctx.call("playwright.page_click", {"selector": {"kind": "role", "value": "button", "name": "查 询", "exact": True}, "role": "operator"})
    await ctx.call("playwright.page_assert_text", {"selector": "main", "text": inputs["empty_result_text"], "role": "operator"})
    records = await ctx.call("playwright.page_list", {"selector": "main a", "role": "operator"})
    if records["truncated"]:
        raise ValueError("查重记录超出读取范围")
    duplicate_count = len([row for row in records["items"] if "机构合约编号：" + suffix in row["text"]])
    if duplicate_count != 0:
        raise ValueError("编号已存在，停止新建合约")
    return ctx.result(data={"contract_suffix": suffix, "timestamp": stamp["compact"], "duplicate_count": duplicate_count})
