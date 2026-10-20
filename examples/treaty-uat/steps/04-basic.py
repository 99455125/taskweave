async def run(ctx, inputs):
    async def field(field_id):
        snapshot = await ctx.call("playwright.page_inspect", {"scope": "full_page", "role": "operator"})
        matches = [e for e in snapshot["elements"] if e.get("id") == field_id and e.get("visible")]
        if len(matches) != 1 or not matches[0].get("preferred_selector"):
            raise ValueError("当前页面字段不唯一或没有验证过的定位器：" + field_id)
        return matches[0]

    async def fill_field(field_id, value):
        element = await field(field_id)
        selector = element["preferred_selector"]
        await ctx.call("playwright.page_fill", {"selector": selector, "value": str(value), "role": "operator"})
        await ctx.call("playwright.page_press", {"selector": selector, "key": "Tab", "role": "operator"})
        if isinstance(value, (int, float)):
            actual = await ctx.call("playwright.page_input_value", {"selector": selector, "role": "operator"})
            if float(actual["value"].replace(",", "")) != float(value):
                raise ValueError("数值字段回读不一致：" + field_id)
        else:
            await ctx.call("playwright.page_assert_value", {"selector": selector, "value": str(value), "role": "operator"})

    async def select_field(field_id, value):
        element = await field(field_id)
        selector = element["preferred_selector"]
        controls = element.get("attributes", {}).get("aria-controls")
        if not controls:
            raise ValueError("字段未提供下拉列表标识：" + field_id)
        ancestors = element.get("ancestor_chain", [])
        if len(ancestors) < 2:
            raise ValueError("字段缺少实际选择控件范围：" + field_id)
        await ctx.call("playwright.page_click", {"selector": ancestors[1]["selector"], "role": "operator"})
        observed = await ctx.call("playwright.page_inspect", {"selector": "[id='" + controls + "']", "include_ancestors": True, "include_descendants": True, "depth": 6, "max_nodes": 100, "role": "operator"})
        matches = []
        for ancestor in observed["dom"]["ancestors"][:3]:
            tree = await ctx.call("playwright.page_inspect", {"selector": ancestor["selector"], "include_descendants": True, "depth": 6, "max_nodes": 300, "role": "operator"})
            queue = [tree["dom"]["root"]]
            while queue:
                node = queue.pop(0)
                queue.extend(node.get("children", []))
                if node.get("visible") and "ant-select-item-option" in node.get("attributes", {}).get("class", "") and "ant-select-item-option-content" not in node.get("attributes", {}).get("class", "") and node.get("name") == str(value):
                    matches.append(node)
            if matches:
                break
        if len(matches) != 1 or not matches[0].get("preferred_selector"):
            raise ValueError("没有唯一实际下拉选项：" + str(value))
        await ctx.call("playwright.page_click", {"selector": matches[0]["preferred_selector"], "role": "operator"})
        await ctx.call("playwright.page_press", {"selector": selector, "key": "Escape", "role": "operator"})
        current = await field(field_id)
        displayed = await ctx.call("playwright.page_text", {"selector": current["ancestor_chain"][1]["selector"], "role": "operator"})
        if str(value) not in displayed["text"]:
            raise ValueError("下拉字段没有显示所选值：" + field_id)

    page = await ctx.call("playwright.page_inspect", {"role": "operator"})
    if page["url"] == "https://ire-uat.shie.com.cn/TreatyManagement/Treaty":
        await ctx.call("playwright.page_click", {"selector": {"kind": "role", "value": "button", "name": "新增合约合同", "exact": True}, "role": "operator"})
        for label in ["财产保险", "比例再保险"]:
            await ctx.call("playwright.page_check", {"selector": {"kind": "label", "value": label, "exact": True}, "checked": True, "role": "operator"})
            await ctx.call("playwright.page_assert_checked", {"selector": {"kind": "label", "value": label, "exact": True}, "checked": True, "role": "operator"})
        await ctx.call("playwright.page_click", {"selector": {"kind": "role", "value": "button", "name": "确 认", "exact": True}, "role": "operator"})
    await ctx.call("playwright.page_assert_url", {"url": "**/TreatyManagement/Treaty/add?**", "role": "operator"})
    await ctx.call("playwright.page_assert_state", {"selector": "#orgBusinessCode", "expected": {"count": 1, "visible": True, "editable": True}, "role": "operator"})
    await fill_field("orgBusinessCode", inputs["contract_suffix"])
    for field_id, value in [("treatyType", inputs["treaty_type"]), ("insuranceCate", inputs["main_insurance_class"]), ("timeZone", inputs["business_timezone_label"]), ("currency", inputs["premium_currency"]), ("renewalFlag", "是" if inputs["is_renewal"] else "否"), ("terminationFlag", inputs["termination_method"])]:
        await select_field(field_id, value)
    for selector, value in [("#startDate", inputs["start_datetime"]), ({"kind": "placeholder", "value": "结束日期", "exact": True}, inputs["end_datetime"])]:
        await ctx.call("playwright.page_click", {"selector": selector, "role": "operator"})
        await ctx.call("playwright.page_assert_state", {"selector": selector, "expected": {"editable": True}, "role": "operator"})
        await ctx.call("playwright.page_fill", {"selector": selector, "value": value, "role": "operator"})
        await ctx.call("playwright.page_press", {"selector": selector, "key": "Tab", "role": "operator"})
        await ctx.call("playwright.page_click", {"selector": {"kind": "role", "value": "button", "name": "确 定", "exact": True}, "role": "operator"})
    await ctx.call("playwright.page_assert_value", {"selector": "#startDate", "value": inputs["start_datetime"], "role": "operator"})
    await ctx.call("playwright.page_assert_value", {"selector": {"kind": "placeholder", "value": "结束日期", "exact": True}, "value": inputs["end_datetime"], "role": "operator"})
    await ctx.call("playwright.page_click", {"selector": "#treatyYear", "role": "operator"})
    await ctx.call("playwright.page_assert_state", {"selector": "#treatyYear", "expected": {"editable": True}, "role": "operator"})
    await fill_field("treatyYear", inputs["business_year"])
    await ctx.call("playwright.page_press", {"selector": "#treatyYear", "key": "Enter", "role": "operator"})
    await fill_field("treatyName", inputs["contract_suffix"])
    await fill_field("epi", inputs["estimated_premium"])
    selector = {"kind": "label", "value": "是" if inputs["is_facultative_obligatory"] else "否", "exact": True, "within": "#facultativeObligatoryTreatyFlag"}
    await ctx.call("playwright.page_check", {"selector": selector, "checked": True, "role": "operator"})
    await ctx.call("playwright.page_assert_checked", {"selector": selector, "checked": True, "role": "operator"})
    await select_field("accountPeriodType", inputs["statement_frequency"])
    for field_id, name in [("furnishedDays", "statement_days"), ("confirmDays", "confirmation_days"), ("settlementDays", "settlement_days")]:
        await fill_field(field_id, inputs[name])
    observed = await ctx.call("playwright.page_inspect", {"role": "operator"})
    return ctx.result(data={"contract_suffix": inputs["contract_suffix"], "form_url": observed["url"]})
