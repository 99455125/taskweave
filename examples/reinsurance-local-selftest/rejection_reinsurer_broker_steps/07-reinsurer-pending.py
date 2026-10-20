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
        await ctx.call("playwright.page_assert_state", {"selector": {"kind": "role", "value": "option", "name": "中文", "exact": True}, "expected": {"count": 1, "visible": True}, "role": role})
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
    async def open_pending():
        current=await ctx.call("playwright.page_inspect",{"role":role})
        if current["url"] in ["http://localhost:9877/TreatyManagement/Treaty/entry", "http://localhost:9877/TreatyManagement/Treaty/audit"]:
            await ctx.call("playwright.page_assert_url",{"url":"**cedentTreatyNo="+inputs["platform_contract_number"]+"&**","role":role})
            return
        current=await ctx.call("playwright.page_inspect",{"role":role})
        if not current["url"].startswith("http://localhost:9877/") or current["url"].endswith("/login"):
            await authenticate()
        if current["url"]!="http://localhost:9877/TreatyManagement/Treaty":
            await ctx.call("playwright.page_open",{"url":"http://localhost:9877/TreatyManagement/Treaty","role":role})
        await ctx.call("playwright.page_assert_state",{"selector":"#查询条件_treatyCode","expected":{"count":1,"visible":True},"role":role})
        await ctx.call("playwright.page_click",{"selector":"text=全部","role":role})
        await ctx.call("playwright.page_fill",{"selector":"#查询条件_treatyCode","value":inputs["platform_contract_number"],"role":role})
        await ctx.call("playwright.page_assert_state",{"selector":{"kind":"role","value":"button","name":"查 询","exact":True},"expected":{"count":1,"enabled":True},"role":role})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"查 询","exact":True},"role":role})
        await ctx.call("playwright.page_assert_text",{"selector":"main","text":"平台合约编号："+inputs["platform_contract_number"],"role":role})
        page_text=await ctx.call("playwright.page_text",{"selector":"main","role":role})
        if page_text["text"].count("平台合约编号："+inputs["platform_contract_number"])!=1:raise ValueError("再保人任务未唯一匹配本轮平台编号")
        tabs=await ctx.call("playwright.page_list",{"selector":{"kind":"role","value":"tab"},"role":role})
        ctx.log("当前任务页签："+str(tabs))
        target={"kind":"role","value":"tab","name":"我的任务","exact":False}
        await ctx.call("playwright.page_assert_state",{"selector":target,"expected":{"count":1,"enabled":True},"role":role})
        await ctx.call("playwright.page_click",{"selector":target,"role":role})
        card='div[class*="list-item_"]:has(a:text-is("平台合约编号：'+inputs["platform_contract_number"]+'"))'
        await ctx.call("playwright.page_assert_state",{"selector":card,"expected":{"count":1,"visible":True},"role":role})
        await ctx.call("playwright.page_assert_text",{"selector":card,"text":"平台合约编号："+inputs["platform_contract_number"],"role":role})
        process={"kind":"role","value":"button","name":"处 理","exact":True,"within":{"kind":"css","value":card}}
        await ctx.call("playwright.page_assert_state",{"selector":process,"expected":{"count":1,"enabled":True},"role":role})
        await ctx.call("playwright.page_click",{"selector":process,"role":role})
    master=await ctx.call("tidb.query",{"sql":"SELECT id,cedent_treaty_no,org_business_code,treaty_name FROM ri_treaty_master WHERE cedent_treaty_no=%s AND org_business_code=%s AND is_deleted='N'","params":[inputs["platform_contract_number"],inputs["contract_suffix"]],"max_rows":2,"title":"独立退回新单归属"})
    if master["truncated"] or master["row_count"]!=1 or master["rows"][0]["treaty_name"]!=inputs["expected_treaty_name"]:raise ValueError("退回新单主表归属或V1名称不符")
    states=await ctx.call("tidb.query",{"sql":"SELECT id,org_code,reinsurance_role,from_id,status,reviewer,biz_id FROM ri_treaty_reinsurer WHERE cedent_treaty_no=%s AND is_deleted='N' ORDER BY id","params":[inputs["platform_contract_number"]],"max_rows":4,"title":"退回前真实上下游与任务状态"})
    r=states["rows"]
    if states["truncated"] or states["row_count"]!=3 or [(x["org_code"],x["reinsurance_role"],str(x["status"])) for x in r]!=[("000050","01","3"),("000053","03","5"),("000045","02","3")]:raise ValueError("独立合约未在首次经纪确认后再保人待确认阶段，停止领取")
    if r[1]["from_id"]!=r[0]["id"] or r[2]["from_id"]!=r[1]["id"] or r[2]["biz_id"]!=inputs["expected_biz_id"] or r[2]["reviewer"] not in [None,"","000045"]:raise ValueError("本轮上下游、Mock业务ID或领取归属不符")
    fee=await ctx.call("tidb.query",{"sql":"SELECT broker_rate FROM ri_treaty_reinsurer WHERE id=%s AND is_deleted='N'","params":[r[2]["id"]],"max_rows":2,"title":"本轮045节点V1经纪费率"})
    if fee["truncated"] or fee["row_count"]!=1 or float(fee["rows"][0]["broker_rate"])!=inputs["expected_broker_rate"]/100:raise ValueError("本轮V1经纪费率不符")
    await authenticate()
    await open_pending()
    await ctx.call("playwright.page_assert_url",{"url":"**/TreatyManagement/Treaty/entry?**cedentTreatyNo="+inputs["platform_contract_number"]+"&**","role":role})
    decision={"kind":"label","value":"退回至经纪人","exact":True}
    await ctx.call("playwright.page_assert_state",{"selector":decision,"expected":{"count":1,"visible":True},"role":role})
    return ctx.result(data={"platform_contract_number":inputs["platform_contract_number"],"contract_suffix":inputs["contract_suffix"],"master_id":master["rows"][0]["id"],"source_table":2,"source_id":r[2]["id"],"broker_id":r[1]["id"],"cedant_id":r[0]["id"],"participants_before":r,"expected_biz_id":inputs["expected_biz_id"],"decision_visible":"退回至经纪人","rejection_performed":False})
