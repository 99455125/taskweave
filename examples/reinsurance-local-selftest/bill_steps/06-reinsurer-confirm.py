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
    role="reinsurer"
    async def state():
        info=await ctx.call("tidb.query",{"sql":"SELECT n.id,n.statement_id,n.net_balance,n.platform_statement_no,n.reviewer,n.review_level,s.statement_status,s.org_code FROM ri_statement_normal n JOIN ri_statement_normal_state s ON s.statement_normal_id=n.id AND s.org_code='000045' AND s.is_deleted='N' WHERE n.id=%s AND n.statement_id=%s AND n.input_org_code='000053' AND n.enter_org_code='000045' AND n.is_deleted='N'","params":[inputs["normal_id"],inputs["statement_id"]],"max_rows":2,"title":"再保人首次确认及审核状态"})
        if info["truncated"] or info["row_count"]!=1:raise ValueError("再保人目标任务不唯一")
        row=info["rows"][0]
        if str(row["net_balance"])!=inputs["expected_balance"]:raise ValueError("再保人金额不符")
        if row["reviewer"] not in [None,"","000045"]:raise ValueError("任务已被其他账号领取")
        return row
    async def open_task(row):
        processing_url=inputs["processing_url"] if row["statement_status"]==3 else inputs["processing_url"].replace("/confirm?","/aduit?").replace("&status=3&","&status=1&")
        if row["reviewer"]!="000045":
            claimed=await ctx.call("process.run",{"executable":"/Users/xiaojuju/Projects/company/bjs/dev-environment/imports/verify-venv/bin/python","args":["/Users/xiaojuju/Projects/company/bjs/dev-environment/test-support/claim_owned_bill.py","--actor","reinsurer","--normal-id",str(inputs["normal_id"]),"--claim"],"timeout_seconds":60,"max_output_bytes":65536})
            if claimed["exit_code"]!=0 or claimed["stdout_truncated"] or claimed["stderr_truncated"]:raise ValueError("正常认证领取失败，不绕过权限或改写状态")
            if processing_url not in claimed["stdout"]:raise ValueError("领取返回的处理页与预期不符")
        await authenticate()
        await ctx.call("playwright.page_open",{"url":processing_url,"role":role})
        await ctx.call("playwright.page_assert_value",{"selector":"#cedentTreatyNo","value":inputs["platform_treaty_no"],"role":role})
        await ctx.call("playwright.page_assert_value",{"selector":"input[id$='-10925282-platformStatementNo']","value":row["platform_statement_no"],"role":role})
    async def decide(label,comment):
        choice={"kind":"label","value":label,"exact":True}
        await ctx.call("playwright.page_assert_state",{"selector":choice,"expected":{"count":1,"visible":True,"enabled":True},"role":role,"timeout_ms":20000})
        await ctx.call("playwright.page_check",{"selector":choice,"checked":True,"role":role})
        await ctx.call("playwright.page_fill",{"selector":"#comments","value":"仅供本地自测 "+inputs["bill_label"]+" "+comment,"role":role})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":role})
        await ctx.call("playwright.page_assert_url",{"url":"**/ContractBill/list","role":role,"timeout_ms":20000})
    before=await state()
    actions=[]
    if before["statement_status"]==3:
        await open_task(before)
        await decide("确认并提交审核","再保首次确认")
        actions.append("first_confirmation")
    for level in [1]:
        row=await state()
        if row["statement_status"]==1 and row["review_level"]==level:
            await open_task(row)
            await decide("本公司同意并确认","再保首次确认审核"+str(level))
            actions.append("audit_"+str(level))
        elif row["statement_status"]==1 and row["review_level"]>level:
            pass
        elif row["statement_status"] in [5,6,8]:
            pass
        else:
            raise ValueError("再保确认/审核状态不符，保留当前业务效果，不重复执行")
    rows=await ctx.call("tidb.query",{"sql":"SELECT n.id,n.input_org_code,n.enter_org_code,n.parent_id,n.net_balance,n.biz_id,n.platform_statement_no,s.org_code,s.statement_status FROM ri_statement_normal n JOIN ri_statement_normal_state s ON s.statement_normal_id=n.id AND s.is_deleted='N' WHERE n.statement_id=%s AND n.is_deleted='N' ORDER BY n.id,s.org_code","params":[inputs["statement_id"]],"max_rows":10,"title":"再保首次一级审核后上下游角色状态"})
    saved=rows["rows"]
    expected_states=[(inputs["upstream_normal_id"],"000050",3),(inputs["upstream_normal_id"],"000053",6),(inputs["normal_id"],"000045",8),(inputs["normal_id"],"000053",8)]
    if rows["truncated"] or [(r["id"],r["org_code"],r["statement_status"]) for r in saved]!=expected_states:raise ValueError("再保确认后角色状态尚未到达，不重复提交")
    if any(str(r["net_balance"])!=inputs["expected_balance"] or not r["biz_id"] for r in saved):raise ValueError("再保确认后余额或Mock bizId不完整")
    if any(r["parent_id"] is not None or (r["input_org_code"],r["enter_org_code"])!=("000050","000053") for r in saved[:2]):raise ValueError("上游总账单关系不符")
    if any(r["parent_id"]!=inputs["upstream_normal_id"] or (r["input_org_code"],r["enter_org_code"])!=("000053","000045") for r in saved[2:]):raise ValueError("下游总账单关系不符")
    items=await ctx.call("tidb.query",{"sql":"SELECT object_id,item_code,item_amount FROM ri_statement_section_item WHERE object_type=0 AND object_id IN (%s,%s) AND is_deleted='N' ORDER BY object_id,item_code","params":[inputs["upstream_normal_id"],inputs["normal_id"]],"max_rows":20,"title":"再保确认后账单科目"})
    expected_items=[(normal,i["code"],i["amount"]) for normal in [inputs["upstream_normal_id"],inputs["normal_id"]] for i in inputs["expected_items"]]
    if items["truncated"] or [(r["object_id"],r["item_code"],str(r["item_amount"])) for r in items["rows"]]!=expected_items:raise ValueError("再保确认后科目金额变化")
    return ctx.result(data={"statement_id":inputs["statement_id"],"normal_id":inputs["normal_id"],"upstream_normal_id":inputs["upstream_normal_id"],"role_states":saved,"items":items["rows"],"actions":actions,"resumed_existing_confirmation":before["statement_status"]==8,"boundary":"本轮正常认证API领取；列表TiFlash未验收。再保确认和一级审核已完成；上游经纪状态6，须继续二次确认及其两级审核。business_mock不能代表真实record或链节点。"})
