async def run(ctx, inputs):
    await ctx.call("playwright.page_fill", {"selector": "#查询条件_treatyCode", "value": inputs["contract_suffix"], "role": "operator"})
    await ctx.call("playwright.page_assert_value", {"selector": "#查询条件_treatyCode", "value": inputs["contract_suffix"], "role": "operator"})
    await ctx.call("playwright.page_click", {"selector": {"kind": "role", "value": "button", "name": "查 询", "exact": True}, "role": "operator"})
    await ctx.call("playwright.page_assert_text", {"selector": "main", "text": "平台合约编号：" + inputs["platform_contract_number"], "role": "operator"})
    links = await ctx.call("playwright.page_list", {"selector": "main a", "role": "operator"})
    if links["truncated"]:
        raise ValueError("列表超出读取范围，不能证明唯一性")
    matched = [row for row in links["items"] if row["text"] == "机构合约编号：" + inputs["contract_suffix"]]
    if len(matched) != 1:
        raise ValueError("编号查询不是唯一记录")
    await ctx.call("playwright.page_assert_state", {"selector": {"kind": "role", "value": "tab", "name": "我的任务", "exact": False}, "expected": {"count": 1, "enabled": True}, "role": "operator"})
    await ctx.call("playwright.page_click", {"selector": {"kind": "role", "value": "tab", "name": "我的任务", "exact": False}, "role": "operator"})
    await ctx.call("playwright.page_assert_state", {"selector": {"kind": "role", "value": "button", "name": "处 理", "exact": True}, "expected": {"count": 1, "enabled": True}, "role": "operator"})
    await ctx.call("playwright.page_click", {"selector": {"kind": "role", "value": "button", "name": "处 理", "exact": True}, "role": "operator"})
    await ctx.call("playwright.page_assert_url", {"url": "**/TreatyManagement/Treaty/audit?**", "role": "operator"})
    await ctx.call("playwright.page_assert_url", {"url": "**/TreatyManagement/Treaty/audit?**cedentTreatyNo=" + inputs["platform_contract_number"] + "&**", "role": "operator"})
    await ctx.call("playwright.page_assert_url", {"url": "**/TreatyManagement/Treaty/audit?**case=audit", "role": "operator"})
    await ctx.call("playwright.page_assert_state", {"selector": "#orgBusinessCode", "expected": {"count": 1, "editable": False}, "role": "operator"})
    await ctx.call("playwright.page_assert_value", {"selector": "#orgBusinessCode", "value": inputs["contract_suffix"], "role": "operator"})
    rows = await ctx.call("playwright.page_list", {"selector": "main table tbody tr", "max_items": 100, "role": "operator"})
    if rows["truncated"]:
        raise ValueError("参与方状态超出读取范围")
    statuses = []
    for participant in inputs["participants"]:
        matching = [row for row in rows["items"] if participant["organization_name"] in row["text"]]
        if len(matching) != 1 or "合同待确认" not in matching[0]["text"]:
            raise ValueError("参与方合同状态不符合实际录入终点")
        statuses.append({"organization_code": participant["organization_code"], "contract_status": "合同待确认"})
    return ctx.result(data={"contract_suffix": inputs["contract_suffix"], "platform_contract_number": inputs["platform_contract_number"], "matched_contract_count": len(matched), "audit_stage": "合约审核", "participant_contract_statuses": statuses})
