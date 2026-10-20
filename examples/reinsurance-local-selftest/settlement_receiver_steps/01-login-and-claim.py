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
    guard=await ctx.call("tidb.query",{"sql":"SELECT s.id,s.settlement_no,s.from_org_code,s.to_org_code,s.currency,s.total_amount,s.institution_settlement_no,s.comments,s.biz_id,r.id AS task_id,r.org_code,r.business_type,r.from_id,r.status,r.reviewer FROM ri_settlement s JOIN ri_settlement_reinsurer r ON r.settlement_no=s.settlement_no AND r.is_deleted='N' WHERE s.id=%s AND s.is_deleted='N' ORDER BY r.business_type","params":[inputs["settlement_id"]],"max_rows":3,"title":"接收方结算领取前置"})
    if guard["truncated"] or guard["row_count"]!=2 or [(r["task_id"],r["org_code"],str(r["status"])) for r in guard["rows"]]!=[(inputs["from_task_id"],"000050","3"),(inputs["to_task_id"],"000053","3")]:raise ValueError("接收方领取前双方未待确认")
    if any(r["settlement_no"]!=inputs["settlement_no"] or r["institution_settlement_no"]!=inputs["run_label"] or r["comments"]!="仅供本地自测 "+inputs["run_label"] or r["currency"]!="SETTLE-CNY" or str(r["total_amount"])!="70000.00" or (r["from_org_code"],r["to_org_code"])!=("000050","000053") or r["biz_id"]!="owned-local-settlement-tw-174791" for r in guard["rows"]):raise ValueError("结算归属、金额或本轮MockID变化")
    receiver=guard["rows"][1]
    if receiver["from_id"]!=inputs["from_task_id"] or receiver["business_type"]!="2" or receiver["reviewer"] not in [None,"","000053"]:raise ValueError("接收任务父子或领取归属变化")
    await authenticate()
    await ctx.call("playwright.page_open",{"url":"http://localhost:9877/SettlementManagement/BillSettlement","role":role})
    card='div[class*="list-item_"]:has(span:text-is("'+inputs["settlement_no"]+'"))'
    await ctx.call("playwright.page_assert_state",{"selector":card,"expected":{"count":1,"visible":True},"role":role})
    await ctx.call("playwright.page_assert_text",{"selector":card,"text":"70,000.00","role":role})
    await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"处 理","exact":True,"within":{"kind":"css","value":card}},"role":role})
    await ctx.call("playwright.page_assert_value",{"selector":"#settlementNo","value":inputs["settlement_no"],"role":role})
    await ctx.call("playwright.page_assert_value",{"selector":"#institutionSettlementNo","value":inputs["run_label"],"role":role})
    after=await ctx.call("tidb.query",{"sql":"SELECT id,org_code,status,from_id,reviewer FROM ri_settlement_reinsurer WHERE id=%s AND settlement_no=%s AND is_deleted='N'","params":[inputs["to_task_id"],inputs["settlement_no"]],"max_rows":2,"title":"接收方正常页面领取结果"})
    if after["truncated"] or after["row_count"]!=1 or after["rows"][0]["reviewer"]!="000053" or after["rows"][0]["from_id"]!=inputs["from_task_id"] or str(after["rows"][0]["status"])!="3":raise ValueError("正常领取结果不符")
    return ctx.result(data={"settlement_id":inputs["settlement_id"],"settlement_no":inputs["settlement_no"],"from_task_id":inputs["from_task_id"],"to_task_id":inputs["to_task_id"],"normal_id":inputs["normal_id"],"run_label":inputs["run_label"],"receiver":after["rows"][0],"claimed":True,"receiver_confirmed":False,"boundary":"仅正常中文登录并领取本轮接收方结算，尚未确认或触发资金接收"})
