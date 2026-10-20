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
        if element.get("attributes", {}).get("aria-expanded") != "true":
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

    async def confirm_upload():
        await ctx.call("playwright.page_assert_text", {"selector": "body", "text": "上传各参与方用印后的合同扫描件，请谨慎上传。", "role": "operator"})
        await ctx.call("playwright.page_click", {"selector": {"kind": "role", "value": "button", "name": "确 定", "exact": True}, "role": "operator"})

    pending = await ctx.call("playwright.page_state", {"selector": {"kind": "role", "value": "button", "name": "确 定", "exact": True}, "role": "operator"})
    if pending["match_count"] == 1 and pending["visible"]:
        await confirm_upload()
    participants = inputs["participants"]
    total = sum(p["share_percent"] for p in participants)
    if abs(total - 100) > 0.000001 or len(set(p["organization_code"] for p in participants)) != len(participants):
        raise ValueError("参与方代码重复或份额合计不等于100%")
    attachment = await ctx.call("file.read", {"path": inputs["attachment_path"], "format": "base64", "max_bytes": 1048576})
    verified_shares = []
    uploaded = 0
    for index, participant in enumerate(participants):
        snapshot = await ctx.call("playwright.page_inspect", {"scope": "full_page", "role": "operator"})
        amounts = [e for e in snapshot["elements"] if e.get("id", "").endswith("_amount") and e.get("visible")]
        if len(amounts) == index:
            await ctx.call("playwright.page_click", {"selector": inputs["add_participant_selector"], "role": "operator"})
            snapshot = await ctx.call("playwright.page_inspect", {"scope": "full_page", "role": "operator"})
            amounts = [e for e in snapshot["elements"] if e.get("id", "").endswith("_amount") and e.get("visible")]
        if len(amounts) <= index or len(amounts) > len(participants):
            raise ValueError("参与方行数与本次新增顺序不符")
        amount = amounts[index]
        row = amount["ancestor_chain"][0]["selector"]["value"].split(" > td:")[0]
        selectors = [e for e in snapshot["elements"] if e.get("role") == "combobox" and e.get("id", "").startswith("rc_select_") and any(a.get("selector", {}).get("value", "").startswith(row + " > ") for a in e.get("ancestor_chain", []))]
        if len(selectors) != 1:
            raise ValueError("当前参与方机构输入框不唯一")
        institution = selectors[0]
        current_institution = await ctx.call("playwright.page_text", {"selector": institution["ancestor_chain"][1]["selector"], "role": "operator"})
        if participant["organization_code"] + "-" + participant["organization_name"] not in current_institution["text"]:
            if institution.get("attributes", {}).get("aria-expanded") != "true":
                await ctx.call("playwright.page_click", {"selector": institution["ancestor_chain"][1]["selector"], "role": "operator"})
            await ctx.call("playwright.page_fill", {"selector": institution["preferred_selector"], "value": "", "role": "operator"})
            await ctx.call("playwright.page_fill", {"selector": institution["preferred_selector"], "value": participant["organization_code"], "role": "operator"})
            await ctx.call("playwright.page_assert_text", {"selector": "body", "text": participant["organization_code"] + "-" + participant["organization_name"], "role": "operator"})
            await select_field(institution["id"], participant["organization_code"] + "-" + participant["organization_name"])
        await fill_field(amount["id"], participant["share_percent"])
        observed_share = await ctx.call("playwright.page_input_value", {"selector": amount["preferred_selector"], "role": "operator"})
        verified_shares.append(float(observed_share["value"].replace(",", "")))
        lead = {"kind": "label", "value": "是", "exact": True, "within": row}
        snapshot = await ctx.call("playwright.page_inspect", {"scope": "full_page", "role": "operator"})
        leads = [e for e in snapshot["elements"] if e.get("type") == "checkbox" and any(a.get("selector", {}).get("value", "").startswith(row + " > ") for a in e.get("ancestor_chain", []))]
        if len(leads) != 1 or leads[0].get("checked") != participant["is_lead"]:
            raise ValueError("首席标志与本次非首席要求不符")
        links = await ctx.call("playwright.page_list", {"selector": row + " a", "role": "operator"})
        existing = [link for link in links["items"] if link["text"].startswith(inputs["attachment_name"].rsplit(".", 1)[0]) and link["text"].endswith(".pdf")]
        if links["total_count"] and len(existing) != 1:
            raise ValueError("参与方已有未知附件，停止覆盖")
        if not existing:
            upload = row + " input[type=file]"
            await ctx.call("playwright.page_assert_state", {"selector": upload, "expected": {"count": 1, "enabled": True}, "role": "operator"})
            await ctx.call("playwright.page_upload", {"selector": upload, "mode": "input", "files": [{"name": inputs["attachment_name"], "mime_type": "application/pdf", "content_base64": attachment["content"]}], "role": "operator"})
            await confirm_upload()
        await ctx.call("playwright.page_assert_state", {"selector": row + " a", "expected": {"count": 1, "visible": True}, "role": "operator"})
        actual_attachment = await ctx.call("playwright.page_text", {"selector": row + " a", "role": "operator"})
        if not actual_attachment["text"].startswith(inputs["attachment_name"].rsplit(".", 1)[0]) or not actual_attachment["text"].endswith(".pdf"):
            raise ValueError("上传后的附件名称不符合预期")
        uploaded += 1
    if abs(sum(verified_shares) - 100) > 0.000001:
        raise ValueError("实际录入份额合计不等于100%")
    return ctx.result(data={"participant_count": len(verified_shares), "total_share_percent": sum(verified_shares), "uploaded_attachment_count": uploaded})
