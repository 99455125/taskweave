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
        controls = element.get("attributes", {}).get("aria-controls")
        if not controls:
            raise ValueError("字段未提供下拉列表标识：" + field_id)
        ancestors = element.get("ancestor_chain", [])
        if len(ancestors) < 2:
            raise ValueError("字段缺少实际选择控件范围：" + field_id)
        if element.get("attributes", {}).get("aria-expanded") != "true":
            await ctx.call("playwright.page_click", {"selector": "[id='" + field_id + "'] >> xpath=ancestor::div[1]", "role": "cedant"})
        observed = await ctx.call("playwright.page_inspect", {"selector": "[id='" + controls + "']", "include_ancestors": True, "include_descendants": True, "depth": 6, "max_nodes": 100, "role": "cedant"})
        matches = []
        for ancestor in observed["dom"]["ancestors"][:3]:
            tree = await ctx.call("playwright.page_inspect", {"selector": ancestor["selector"], "include_descendants": True, "depth": 6, "max_nodes": 300, "role": "cedant"})
            queue = [tree["dom"]["root"]]
            while queue:
                node = queue.pop(0)
                queue.extend(node.get("children", []))
                if node.get("visible") and "ant-select-item-option" in node.get("attributes", {}).get("class", "") and "ant-select-item-option-content" not in node.get("attributes", {}).get("class", "") and (node.get("name") == str(value) or node.get("name", "").startswith(str(value) + "-")):
                    matches.append(node)
            if matches:
                break
        if len(matches) != 1 or not matches[0].get("preferred_selector"):
            raise ValueError("没有唯一实际下拉选项：" + str(value))
        await ctx.call("playwright.page_click", {"selector": matches[0]["preferred_selector"], "role": "cedant"})
        await ctx.call("playwright.page_press", {"selector": selector, "key": "Escape", "role": "cedant"})
        current = await field(field_id)
        displayed = await ctx.call("playwright.page_text", {"selector": "#" + field_id + " >> xpath=ancestor::div[1]", "role": "cedant"})
        if str(value) not in displayed["text"]:
            raise ValueError("下拉字段没有显示所选值：" + field_id)

    async def row_for(amount_id):
        return {"kind":"css","value":"[id='"+amount_id+"'] >> xpath=ancestor::tr[1]"}

    async def choose_org(amount_id, code):
        row = await row_for(amount_id)
        observed = await ctx.call("playwright.page_inspect", {"selector":row,"include_descendants":True,"depth":6,"max_nodes":300,"role":"cedant"})
        prefix = observed["dom"]["root"]["selector"]["value"]
        choices = [e for e in observed["elements"] if e.get("id", "").startswith("rc_select_") and any(a["selector"].get("value", "").startswith(prefix+" > ") for a in e.get("ancestor_chain", []))]
        if len(choices)!=1:
            raise ValueError("参与方机构选择字段必须唯一")
        element=choices[0]
        wrapper="[id='"+element["id"]+"'] >> xpath=ancestor::div[1]"
        displayed=await ctx.call("playwright.page_text",{"selector":wrapper,"role":"cedant"})
        if code+"-" not in displayed["text"]:
            if element.get("attributes",{}).get("aria-expanded")!="true":
                await ctx.call("playwright.page_click",{"selector":wrapper,"role":"cedant"})
            await ctx.call("playwright.page_fill",{"selector":element["preferred_selector"],"value":"","role":"cedant"})
            await ctx.call("playwright.page_fill",{"selector":element["preferred_selector"],"value":code,"role":"cedant"})
            await ctx.call("playwright.page_assert_text",{"selector":"body","text":code+"-","role":"cedant"})
            await select_field(element["id"],code)
        await ctx.call("playwright.page_assert_text",{"selector":row,"text":code+"-","role":"cedant"})
        return row

    snapshot=await ctx.call("playwright.page_inspect",{"role":"cedant"})
    amounts=[e for e in snapshot["elements"] if e.get("id","").endswith("_amount") and e.get("visible")]
    if len(amounts) not in [1,2]:
        raise ValueError("本地三方演示须一行经纪人与一行下游再保人")
    broker_id=amounts[0]["id"]
    broker_row=await choose_org(broker_id,inputs["broker_code"])
    await ctx.call("playwright.page_assert_text",{"selector":broker_row,"text":"经纪人","role":"cedant"})
    if len(amounts)==1:
        observed=await ctx.call("playwright.page_inspect",{"selector":broker_row,"include_descendants":True,"depth":6,"max_nodes":300,"role":"cedant"})
        queue=[observed["dom"]["root"]];add=[]
        while queue:
            node=queue.pop(0);queue.extend(node.get("children",[]))
            if node.get("tag")=="img" and node.get("selector",{}).get("value","").endswith(" > td:nth-of-type(7) > div:nth-of-type(1) > div:nth-of-type(1) > img:nth-of-type(1)"):
                add.append(node)
        if len(add)!=1:
            raise ValueError("当前经纪行的新增下游图标必须与已采集DOM唯一匹配")
        await ctx.call("playwright.page_click",{"selector":add[0]["preferred_selector"],"role":"cedant"})
        await ctx.call("playwright.page_assert_state",{"selector":"input[id$='_amount']","expected":{"count":2},"role":"cedant"})
    snapshot=await ctx.call("playwright.page_inspect",{"role":"cedant"})
    amounts=[e for e in snapshot["elements"] if e.get("id","").endswith("_amount") and e.get("visible")]
    if len(amounts)!=2:raise ValueError("下游再保人行未生成")
    child_id=amounts[1]["id"]
    child_row=await choose_org(child_id,inputs["reinsurer_code"])
    direct={"kind":"label","value":"再保人自行操作","exact":True,"within":child_row}
    await ctx.call("playwright.page_check",{"selector":direct,"checked":True,"role":"cedant"})
    await ctx.call("playwright.page_assert_checked",{"selector":direct,"checked":True,"role":"cedant"})
    await fill_field(child_id,inputs["share_percent"])
    # Current cedant page intentionally hides brokerage rate; broker confirms it later.
    observed_share = await ctx.call("playwright.page_inspect",{"selector":"[id='"+broker_id+"']","depth":0,"max_nodes":1,"role":"cedant"})
    parent_share = {"value":observed_share["dom"]["root"].get("value","")}
    if not parent_share["value"] or float(parent_share["value"].replace(",","")) != float(inputs["share_percent"]):
        raise ValueError("经纪行汇总份额不一致：" + parent_share["value"])
    snapshot=await ctx.call("playwright.page_inspect",{"role":"cedant"})
    for check in [e for e in snapshot["elements"] if e.get("type")=="checkbox" and e.get("visible")]:
        if check.get("checked") is not False:raise ValueError("本次均不设首席")
    attachment=await ctx.call("file.read",{"path":inputs["attachment_path"],"format":"base64","max_bytes":1048576})
    for row in [broker_row]:
        links={"kind":"css","value":"a","within":row}
        listed=await ctx.call("playwright.page_list",{"selector":links,"role":"cedant"})
        if listed["truncated"]:raise ValueError("参与方附件列表不完整")
        matched=[v for v in listed["items"] if v["text"].startswith(inputs["attachment_name"].rsplit(".",1)[0]) and v["text"].endswith(".pdf")]
        if listed["total_count"] and len(matched)!=1:raise ValueError("已有未知合同附件，停止覆盖")
        if matched and inputs.get("refresh_test_attachment", False):
            remove = {"kind":"css","value":"button[title='删除文件']","within":row}
            await ctx.call("playwright.page_assert_state",{"selector":remove,"expected":{"count":1,"enabled":True},"role":"cedant"})
            await ctx.call("playwright.page_click",{"selector":remove,"role":"cedant"})
            await ctx.call("playwright.page_assert_state",{"selector":links,"expected":{"count":0},"role":"cedant"})
        if not matched or inputs.get("refresh_test_attachment", False):
            upload={"kind":"css","value":"input[type=file]","within":row}
            await ctx.call("playwright.page_upload",{"selector":upload,"mode":"input","files":[{"name":inputs["attachment_name"],"mime_type":"application/pdf","content_base64":attachment["content"]}],"role":"cedant"})
            await ctx.call("playwright.page_assert_text",{"selector":"body","text":"上传各参与方用印后的合同扫描件，请谨慎上传。","role":"cedant"})
            await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"确 定","exact":True},"role":"cedant"})
        row_text=await ctx.call("playwright.page_text",{"selector":row,"role":"cedant"})
        ctx.log("附件现场："+row_text["text"])
        await ctx.call("playwright.page_assert_text",{"selector":links,"text":inputs["attachment_name"].rsplit(".",1)[0],"role":"cedant"})
        upload_link = await ctx.call("playwright.page_inspect", {"selector":links,"include_ancestors":True,"depth":0,"max_nodes":1,"role":"cedant"})
        states=[]
        for ancestor in upload_link["dom"]["ancestors"]:
            node = await ctx.call("playwright.page_inspect", {"selector":ancestor["selector"],"depth":0,"max_nodes":1,"role":"cedant"})
            classes=node["dom"]["root"].get("attributes",{}).get("class", "").split()
            if "ant-upload-list-item" in classes: states.append(classes)
        if len(states)!=1 or "ant-upload-list-item-done" not in states[0]:
            raise ValueError("附件尚无明确上传完成状态：" + str(states))
    await ctx.call("playwright.page_assert_state", {"selector":{"kind":"css","value":"input[type=file]","within":child_row},"expected":{"count":1,"enabled":False},"role":"cedant"})
    return ctx.result(data={"downstream_attachment_stage":"由经纪人后续上传；当前分出方字段禁用", "broker_code":inputs["broker_code"],"reinsurer_code":inputs["reinsurer_code"],"broker_amount_id":broker_id,"reinsurer_amount_id":child_id,"share_percent":inputs["share_percent"],"broker_rate_to_enter_at_broker_confirmation":inputs["broker_rate"],"uploaded_attachments":1,"reinsurer_involved":True,"leader":False})
