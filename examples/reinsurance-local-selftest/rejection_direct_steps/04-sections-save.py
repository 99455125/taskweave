async def run(ctx, inputs):
    async def field(field_id):
        snapshot = await ctx.call("playwright.page_inspect", {"scope": "full_page", "role": "cedant"})
        matches = [e for e in snapshot["elements"] if e.get("id") == field_id and e.get("visible")]
        if len(matches) != 1 or not matches[0].get("preferred_selector"):
            raise ValueError("当前页面字段不唯一或没有验证过的定位器：" + field_id)
        return matches[0]

    async def fill_field(field_id, value):
        element = await field(field_id)
        selector = element["preferred_selector"]
        await ctx.call("playwright.page_fill", {"selector": selector, "value": str(value), "role": "cedant"})
        await ctx.call("playwright.page_press", {"selector": selector, "key": "Tab", "role": "cedant"})
        if isinstance(value, (int, float)):
            actual = await ctx.call("playwright.page_input_value", {"selector": selector, "role": "cedant"})
            if float(actual["value"].replace(",", "")) != float(value):
                raise ValueError("数值字段回读不一致：" + field_id)
        else:
            await ctx.call("playwright.page_assert_value", {"selector": selector, "value": str(value), "role": "cedant"})

    async def select_field(field_id, value):
        element = await field(field_id)
        selector = element["preferred_selector"]
        if field_id == "insuranceTypeCodes":
            selected = await ctx.call("playwright.page_text", {"selector": element["ancestor_chain"][3]["selector"], "role": "cedant"})
            if str(value) in selected["text"]:
                return
        controls = element.get("attributes", {}).get("aria-controls")
        if not controls:
            raise ValueError("字段未提供下拉列表标识：" + field_id)
        ancestors = element.get("ancestor_chain", [])
        if len(ancestors) < 2:
            raise ValueError("字段缺少实际选择控件范围：" + field_id)
        if element.get("attributes", {}).get("aria-expanded") != "true":
            await ctx.call("playwright.page_click", {"selector": ancestors[3 if field_id == "insuranceTypeCodes" else 1]["selector"], "role": "cedant"})
        root_selector = "[id='" + controls + "']"
        root_state = await ctx.call("playwright.page_state", {"selector": root_selector, "role": "cedant"})
        matches = []
        for root_index in range(root_state["match_count"]):
            observed = await ctx.call("playwright.page_inspect", {"selector": {"kind": "css", "value": root_selector, "nth": root_index}, "include_ancestors": True, "include_descendants": True, "depth": 6, "max_nodes": 100, "role": "cedant"})
            for ancestor in observed["dom"]["ancestors"][:3]:
                tree = await ctx.call("playwright.page_inspect", {"selector": ancestor["selector"], "include_descendants": True, "depth": 6, "max_nodes": 300, "role": "cedant"})
                queue = [tree["dom"]["root"]]
                while queue:
                    node = queue.pop(0)
                    queue.extend(node.get("children", []))
                    if node.get("visible") and "ant-select-item-option" in node.get("attributes", {}).get("class", "") and "ant-select-item-option-content" not in node.get("attributes", {}).get("class", "") and node.get("name") == str(value):
                        matches.append(node)
                if matches:
                    break
            if matches:
                break
        if len(matches) != 1 or not matches[0].get("preferred_selector"):
            raise ValueError("没有唯一实际下拉选项：" + str(value))
        await ctx.call("playwright.page_click", {"selector": matches[0]["preferred_selector"], "role": "cedant"})
        current = await field(field_id)
        await ctx.call("playwright.page_press", {"selector": current["preferred_selector"], "key": "Escape", "role": "cedant"})
        current = await field(field_id)
        displayed = await ctx.call("playwright.page_text", {"selector": current["ancestor_chain"][3 if field_id == "insuranceTypeCodes" else 1]["selector"], "role": "cedant"})
        if str(value) not in displayed["text"]:
            raise ValueError("下拉字段没有显示所选值：" + field_id)

    sections = inputs["sections"]
    if len(sections) != 2:
        raise ValueError("本 Demo 须录入两个分项")
    categories = []
    for index, section in enumerate(sections):
        tabs = await ctx.call("playwright.page_list", {"selector": {"kind": "role", "value": "tab"}, "role": "cedant"})
        if tabs["total_count"] > len(sections) or tabs["truncated"]:
            raise ValueError("已有分项数量超出本次录入范围")
        if tabs["total_count"] == index:
            await ctx.call("playwright.page_click", {"selector": {"kind": "role", "value": "button", "name": "Add tab", "exact": True}, "role": "cedant"})
        await ctx.call("playwright.page_assert_state", {"selector": {"kind": "role", "value": "tab", "nth": index}, "expected": {"count": 1, "visible": True}, "role": "cedant"})
        await ctx.call("playwright.page_click", {"selector": {"kind": "role", "value": "tab", "nth": index}, "role": "cedant"})
        await fill_field("sectionType", section["category"])
        for insurance_type in section["insurance_types"]:
            await select_field("insuranceTypeCodes", insurance_type)
        await select_field("sumInsuredCurrency", section["currency"])
        await fill_field("maxLimits", section["maximum_limit"])
        await select_field("commissionType", section["commission_type"])
        if section["commission_type"] == "固定费率":
            await fill_field("commisionRate", section["fixed_commission_rate"])
        elif section["commission_type"] == "浮动费率":
            await fill_field("commisionRate", section["advance_commission_rate"])
            await fill_field("maxCommissionRate", section["commission_upper_limit"])
            await fill_field("minCommissionRate", section["commission_lower_limit"])
        else:
            raise ValueError("未观察到的手续费类型")
        if inputs["treaty_type"] != "成数合约":
            for field_id, key in [("lines", "surplus_lines"), ("maxNetRetention", "maximum_net_retention"), ("maxGrossRetention", "maximum_gross_retention"), ("cessionShareRate", "quota_ceded_share_percent"), ("cessionCapacity", "ceded_underwriting_capacity")]:
                await fill_field(field_id, section[key])
        snapshot = await ctx.call("playwright.page_inspect", {"scope": "full_page", "role": "cedant"})
        radios = [e for e in snapshot["elements"] if e.get("type") == "radio" and e.get("name") == ("是" if section["loss_sharing"] else "否") and any(a.get("id") == "lossSharingFlag" for a in e.get("ancestor_chain", []))]
        if len(radios) != 1 or not radios[0].get("preferred_selector"):
            raise ValueError("当前分项损失分摊选项不唯一")
        await ctx.call("playwright.page_check", {"selector": radios[0]["preferred_selector"], "checked": True, "role": "cedant"})
        await ctx.call("playwright.page_assert_checked", {"selector": radios[0]["preferred_selector"], "checked": True, "role": "cedant"})
        actual = await ctx.call("playwright.page_input_value", {"selector": (await field("sectionType"))["preferred_selector"], "role": "cedant"})
        categories.append(actual["value"])
    attachments = await ctx.call("playwright.page_list", {"selector":"main a","role":"cedant"})
    if len([a for a in attachments["items"] if a["text"].startswith("tw-local-treaty-demo") and a["text"].endswith(".pdf")]) != 1:
        raise ValueError("本阶段直连再保人合同附件须恰好1个成功链接")
    await ctx.call("playwright.page_assert_value", {"selector": "#orgBusinessCode", "value": inputs["contract_suffix"], "role": "cedant"})
    current = await ctx.call("playwright.page_inspect", {"role": "cedant"})
    if current["url"].endswith("/TreatyManagement/Treaty/add"):
        confirm = {"kind": "role", "value": "button", "name": "确 定", "exact": True}
        pending = await ctx.call("playwright.page_state", {"selector": confirm, "role": "cedant"})
        if not (pending["match_count"] == 1 and pending["visible"]):
            await ctx.call("playwright.page_click", {"selector": {"kind": "role", "value": "button", "name": "保 存", "exact": True}, "role": "cedant"})
        await ctx.call("playwright.page_assert_text", {"selector": "body", "text": "保存后[合约起止期]和[业务年度]将不可修改，请确认", "role": "cedant"})
        await ctx.call("playwright.page_click", {"selector": confirm, "role": "cedant"})
    await ctx.call("playwright.page_assert_url", {"url": "**/TreatyManagement/Treaty/edit?**", "role": "cedant"})
    await ctx.call("playwright.page_assert_text", {"selector": "main", "text": "000050-", "role": "cedant"})
    body = await ctx.call("playwright.page_text", {"selector": "main", "role": "cedant"})
    number = body["text"].split("平台合约编号", 1)[1].split("保险种类", 1)[0].replace("：", "").replace(":", "").strip()
    if not number.startswith("000050-") or any(c.isspace() for c in number):
        raise ValueError("保存后页面未显示唯一的本机构平台合约编号")
    await ctx.call("playwright.page_assert_url", {"url": "**/TreatyManagement/Treaty/edit?**cedentTreatyNo=" + number + "&**", "role": "cedant"})
    await ctx.call("playwright.page_assert_value", {"selector": "#orgBusinessCode", "value": inputs["contract_suffix"], "role": "cedant"})
    await ctx.call("playwright.page_assert_state", {"selector": "#startDate", "expected": {"count": 1, "editable": False}, "role": "cedant"})
    observed = await ctx.call("playwright.page_inspect", {"role": "cedant"})
    return ctx.result(data={"platform_contract_number": number, "contract_suffix": inputs["contract_suffix"], "edit_url": observed["url"], "section_count": len(categories), "section_categories": categories})
