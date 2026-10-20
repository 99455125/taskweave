async def run(ctx, inputs):
    await ctx.call("playwright.page_assert_url", {"url": "**/TreatyManagement/Treaty/edit?**cedentTreatyNo=" + inputs["platform_contract_number"] + "&**", "role": "operator"})
    choice = {"kind": "label", "value": "确认并提交审核", "exact": True}
    await ctx.call("playwright.page_check", {"selector": choice, "checked": True, "role": "operator"})
    await ctx.call("playwright.page_assert_checked", {"selector": choice, "checked": True, "role": "operator"})
    await ctx.call("playwright.page_fill", {"selector": "#comments", "value": inputs["audit_comment"], "role": "operator"})
    await ctx.call("playwright.page_assert_value", {"selector": "#comments", "value": inputs["audit_comment"], "role": "operator"})
    await ctx.call("playwright.page_click", {"selector": {"kind": "role", "value": "button", "name": "提 交", "exact": True}, "role": "operator"})
    await ctx.call("playwright.page_assert_url", {"url": "**/TreatyManagement/Treaty", "role": "operator"})
    await ctx.call("playwright.page_assert_state", {"selector": "#查询条件_treatyCode", "expected": {"count": 1, "visible": True}, "role": "operator"})
    return ctx.result(data={"platform_contract_number": inputs["platform_contract_number"], "submission_status": "提交后已返回合约列表，审核终态由下一步核对"})
