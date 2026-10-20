async def run(ctx, inputs):
    await ctx.call("playwright.page_assert_value", {"selector": "#orgBusinessCode", "value": inputs["contract_suffix"], "role": "operator"})
    current = await ctx.call("playwright.page_inspect", {"role": "operator"})
    if current["url"].endswith("/TreatyManagement/Treaty/add"):
        confirm = {"kind": "role", "value": "button", "name": "确 定", "exact": True}
        pending = await ctx.call("playwright.page_state", {"selector": confirm, "role": "operator"})
        if not (pending["match_count"] == 1 and pending["visible"]):
            await ctx.call("playwright.page_click", {"selector": {"kind": "role", "value": "button", "name": "保 存", "exact": True}, "role": "operator"})
        await ctx.call("playwright.page_assert_text", {"selector": "body", "text": "保存后[合约起止期]和[业务年度]将不可修改，请确认", "role": "operator"})
        await ctx.call("playwright.page_click", {"selector": confirm, "role": "operator"})
    await ctx.call("playwright.page_assert_url", {"url": "**/TreatyManagement/Treaty/edit?**", "role": "operator"})
    await ctx.call("playwright.page_assert_text", {"selector": "main", "text": "000027-", "role": "operator"})
    body = await ctx.call("playwright.page_text", {"selector": "main", "role": "operator"})
    number = body["text"].split("平台合约编号", 1)[1].split("保险种类", 1)[0].replace("：", "").replace(":", "").strip()
    if not number.startswith("000027-") or any(c.isspace() for c in number):
        raise ValueError("保存后页面未显示唯一的本机构平台合约编号")
    await ctx.call("playwright.page_assert_url", {"url": "**/TreatyManagement/Treaty/edit?**cedentTreatyNo=" + number + "&**", "role": "operator"})
    await ctx.call("playwright.page_assert_value", {"selector": "#orgBusinessCode", "value": inputs["contract_suffix"], "role": "operator"})
    await ctx.call("playwright.page_assert_state", {"selector": "#startDate", "expected": {"count": 1, "editable": False}, "role": "operator"})
    observed = await ctx.call("playwright.page_inspect", {"role": "operator"})
    return ctx.result(data={"platform_contract_number": number, "contract_suffix": inputs["contract_suffix"], "edit_url": observed["url"]})
