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
    role=inputs["role"]
    guard=await ctx.call("tidb.query",{"sql":"SELECT s.id,s.institution_settlement_no,s.comments,s.currency,s.total_amount,r.id AS task_id,r.org_code,r.status,r.review_level,r.reviewer FROM ri_settlement s JOIN ri_settlement_reinsurer r ON r.settlement_no=s.settlement_no AND r.is_deleted='N' WHERE s.id=%s AND s.settlement_no=%s AND s.from_org_code='000050' AND s.to_org_code='000053' AND s.is_deleted='N' ORDER BY r.business_type","params":[inputs["settlement_id"],inputs["settlement_no"]],"max_rows":3,"title":"接收方一级审核双任务守卫"})
    if guard["truncated"] or guard["row_count"]!=2 or [(r["task_id"],r["org_code"],str(r["status"])) for r in guard["rows"]]!=[(inputs["from_task_id"],"000050","3"),(inputs["to_task_id"],"000053","1")]:raise ValueError("审核前双方任务状态不符")
    if any(r["institution_settlement_no"]!=inputs["run_label"] or r["comments"]!="仅供本地自测 "+inputs["run_label"] or r["currency"]!="SETTLE-CNY" or str(r["total_amount"])!=inputs["expected_amount"] for r in guard["rows"]):raise ValueError("审核前归属或金额变化")
    sender=guard["rows"][1]
    if str(sender["review_level"])!="1" or sender["reviewer"] not in [None,"","000053"]:raise ValueError("审核级次或领取人变化，不重复一级审核")
    await authenticate()
    await ctx.call("playwright.page_open",{"url":"http://localhost:9877/SettlementManagement/BillSettlement","role":role})
    await ctx.call("playwright.page_assert_text",{"selector":"body","text":"用户名称000053","role":role})
    card='div[class*="list-item_"]:has(span:text-is("'+inputs["settlement_no"]+'"))'
    await ctx.call("playwright.page_assert_state",{"selector":card,"expected":{"count":1,"visible":True},"role":role})
    await ctx.call("playwright.page_assert_text",{"selector":card,"text":"70,000.00","role":role})
    await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"处 理","exact":True,"within":{"kind":"css","value":card}},"role":role})
    await ctx.call("playwright.page_assert_value",{"selector":"#settlementNo","value":inputs["settlement_no"],"role":role})
    await ctx.call("playwright.page_assert_value",{"selector":"#institutionSettlementNo","value":inputs["run_label"],"role":role})
    decision={"kind":"label","value":"确认并提交审核","exact":True}
    await ctx.call("playwright.page_assert_state",{"selector":decision,"expected":{"count":1,"visible":True},"role":role})
    await ctx.call("playwright.page_check",{"selector":decision,"checked":True,"role":role})
    await ctx.call("playwright.page_fill",{"selector":"#auditComments","value":"仅供本地自测 接收方一级审核 "+inputs["run_label"],"role":role})
    await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":role})
    await ctx.call("playwright.page_assert_url",{"url":"http://localhost:9877/SettlementManagement/BillSettlement","role":role})
    after=await ctx.call("tidb.query",{"sql":"SELECT id,org_code,status,review_level,reviewer,biz_id FROM ri_settlement_reinsurer WHERE settlement_no=%s AND is_deleted='N' ORDER BY business_type","params":[inputs["settlement_no"]],"max_rows":3,"title":"接收方一级审核后状态"})
    if after["truncated"] or [(r["id"],r["org_code"],str(r["status"])) for r in after["rows"]]!=[(inputs["from_task_id"],"000050","3"),(inputs["to_task_id"],"000053","1")] or str(after["rows"][1]["review_level"])!="2":raise ValueError("一级审核后状态不符；保留实际结果，不重复审核")
    return ctx.result(data={"settlement_id":inputs["settlement_id"],"settlement_no":inputs["settlement_no"],"from_task_id":inputs["from_task_id"],"to_task_id":inputs["to_task_id"],"run_label":inputs["run_label"],"role_states":after["rows"],"first_audit_completed":True,"receiver_audit_completed":False})
