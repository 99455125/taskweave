async def run(ctx, inputs):
    async def authenticate():
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
    role="broker"
    async def state():
        info=await ctx.call("tidb.query",{"sql":"SELECT n.id,n.statement_id,n.net_balance,n.platform_statement_no,n.reviewer,n.review_level,s.statement_status,s.org_code FROM ri_statement_normal n JOIN ri_statement_normal_state s ON s.statement_normal_id=n.id AND s.org_code='000053' AND s.is_deleted='N' WHERE n.id=%s AND n.statement_id=%s AND n.input_org_code='000050' AND n.enter_org_code='000053' AND n.is_deleted='N'","params":[inputs["normal_id"],inputs["statement_id"]],"max_rows":2,"title":"经纪人二次确认前置"})
        if info["truncated"] or info["row_count"]!=1:raise ValueError("经纪人目标任务不唯一")
        row=info["rows"][0]
        if str(row["net_balance"])!=inputs["expected_balance"]:raise ValueError("经纪人金额不符")
        if row["reviewer"] not in [None,"","000053"]:raise ValueError("任务已被其他账号领取")
        return row
    async def open_task(row):
        processing_url=inputs["processing_url"]
        if row["reviewer"]!="000053":
            claimed=await ctx.call("process.run",{"executable":"/Users/xiaojuju/Projects/company/bjs/dev-environment/imports/verify-venv/bin/python","args":["/Users/xiaojuju/Projects/company/bjs/dev-environment/test-support/claim_owned_bill.py","--actor","broker","--normal-id",str(inputs["normal_id"]),"--claim"],"timeout_seconds":60,"max_output_bytes":65536})
            if claimed["exit_code"]!=0 or claimed["stdout_truncated"] or claimed["stderr_truncated"]:raise ValueError("正常认证领取失败，不绕过权限或改写状态")
            if processing_url not in claimed["stdout"]:raise ValueError("领取返回的处理页与预期不符")
        await authenticate()
        await ctx.call("playwright.page_open",{"url":processing_url,"role":role})
        await ctx.call("playwright.page_assert_value",{"selector":"#cedentTreatyNo","value":inputs["platform_treaty_no"],"role":role})
        await ctx.call("playwright.page_assert_value",{"selector":"input[id$='-10925281-platformStatementNo']","value":row["platform_statement_no"],"role":role})
    before=await state()
    completed=before["statement_status"]==inputs["after_status"] and (inputs["after_status"]==8 or before["review_level"]==inputs["after_level"])
    if not completed:
        if before["statement_status"]!=inputs["before_status"] or before["review_level"]!=inputs.get("before_level"):raise ValueError("经纪二次流程当前阶段不符，不重复前序提交")
        await open_task(before)
        choice={"kind":"label","value":inputs["decision_label"],"exact":True}
        await ctx.call("playwright.page_assert_state",{"selector":choice,"expected":{"count":1,"visible":True,"enabled":True},"role":role,"timeout_ms":20000})
        await ctx.call("playwright.page_check",{"selector":choice,"checked":True,"role":role})
        await ctx.call("playwright.page_fill",{"selector":"#comments","value":"仅供本地自测 "+inputs["bill_label"]+" "+inputs["phase_name"],"role":role})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":role})
        await ctx.call("playwright.page_assert_url",{"url":"**/ContractBill/list","role":role,"timeout_ms":20000})
    after=await state()
    if after["statement_status"]!=inputs["after_status"] or (inputs["after_status"]!=8 and after["review_level"]!=inputs["after_level"]):raise ValueError("本轮经纪二次动作状态尚未到达，不重复提交")
    rows=await ctx.call("tidb.query",{"sql":"SELECT n.id,n.input_org_code,n.enter_org_code,n.parent_id,n.net_balance,n.biz_id,n.platform_statement_no,s.org_code,s.statement_status FROM ri_statement_normal n JOIN ri_statement_normal_state s ON s.statement_normal_id=n.id AND s.is_deleted='N' WHERE n.statement_id=%s AND n.is_deleted='N' ORDER BY n.id,s.org_code","params":[inputs["statement_id"]],"max_rows":10,"title":"经纪二次动作后上下游角色状态"})
    saved=rows["rows"]
    source_status=8 if inputs["after_status"]==8 else 3
    expected=[(inputs["normal_id"],"000050",source_status),(inputs["normal_id"],"000053",inputs["after_status"]),(inputs["downstream_normal_id"],"000045",8),(inputs["downstream_normal_id"],"000053",8)]
    if rows["truncated"] or [(r["id"],r["org_code"],r["statement_status"]) for r in saved]!=expected:raise ValueError("经纪二次动作后实际角色状态不符")
    if any(str(r["net_balance"])!=inputs["expected_balance"] or not r["biz_id"] for r in saved):raise ValueError("本轮金额或Mock bizId不完整")
    if any(r["parent_id"] is not None or (r["input_org_code"],r["enter_org_code"])!=("000050","000053") for r in saved[:2]):raise ValueError("上游总账单关系不符")
    if any(r["parent_id"]!=inputs["normal_id"] or (r["input_org_code"],r["enter_org_code"])!=("000053","000045") for r in saved[2:]):raise ValueError("下游总账单关系不符")
    items=await ctx.call("tidb.query",{"sql":"SELECT object_id,item_code,item_amount FROM ri_statement_section_item WHERE object_type=0 AND object_id IN (%s,%s) AND is_deleted='N' ORDER BY object_id,item_code","params":[inputs["normal_id"],inputs["downstream_normal_id"]],"max_rows":20,"title":"经纪二次动作后账单科目"})
    expected_items=[(normal,i["code"],i["amount"]) for normal in [inputs["normal_id"],inputs["downstream_normal_id"]] for i in inputs["expected_items"]]
    if items["truncated"] or [(r["object_id"],r["item_code"],str(r["item_amount"])) for r in items["rows"]]!=expected_items:raise ValueError("经纪二次动作后科目金额变化")
    return ctx.result(data={"statement_id":inputs["statement_id"],"normal_id":inputs["normal_id"],"phase":inputs["phase_name"],"after":after,"role_states":saved,"items":items["rows"],"resumed_existing_action":completed,"boundary":"本地正常认证领取/页面决策；列表TiFlash未验收。业务Mock与真实record来源及链节点分列。"})
