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
    async def open_pending():
        current=await ctx.call("playwright.page_inspect",{"role":role})
        if current["url"] in ["http://localhost:9877/TreatyManagement/Treaty/entry", "http://localhost:9877/TreatyManagement/Treaty/audit", "http://localhost:9877/TreatyManagement/Treaty/confirm"]:
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
        if page_text["text"].count("平台合约编号："+inputs["platform_contract_number"])!=1:raise ValueError("经纪任务未唯一匹配本轮平台编号")
        tabs=await ctx.call("playwright.page_list",{"selector":{"kind":"role","value":"tab"},"role":role})
        ctx.log("当前任务页签："+str(tabs))
        target={"kind":"role","value":"tab","name":"我的任务","exact":False}
        await ctx.call("playwright.page_assert_state",{"selector":target,"expected":{"count":1,"enabled":True},"role":role})
        await ctx.call("playwright.page_click",{"selector":target,"role":role})
        process={"kind":"role","value":"button","name":"处 理","exact":True}
        await ctx.call("playwright.page_assert_state",{"selector":process,"expected":{"count":1,"enabled":True},"role":role})
        await ctx.call("playwright.page_click",{"selector":process,"role":role})
    async def states():
        result=await ctx.call("tidb.query",{"sql":"SELECT id,org_code,status,review_level,file_status,org_business_code,biz_id FROM ri_treaty_reinsurer WHERE cedent_treaty_no=%s AND is_deleted='N' ORDER BY id","params":[inputs["platform_contract_number"]],"max_rows":10,"title":"本轮二次确认状态"})
        if result["truncated"] or [r["org_code"] for r in result["rows"]]!=["000050","000053","000045"]:raise ValueError("本轮三方状态不唯一")
        return result["rows"]
    before=await states()
    if before[1]["status"]!="8":
        if before[1]["status"]!="9" or before[1]["review_level"]!="2":raise ValueError("本轮二次确认须处于二级审核9/2")
        await open_pending()
        await ctx.call("playwright.page_assert_url",{"url":"**/TreatyManagement/Treaty/audit?**","role":role})
        await ctx.call("playwright.page_assert_state",{"selector":{"kind":"label","value":"本公司同意并确认","exact":True},"expected":{"count":1,"enabled":True},"role":role})
        snapshot=await ctx.call("playwright.page_inspect",{"scope":"full_page","role":role})
        choices=[e for e in snapshot["elements"] if e.get("type")=="radio" and e.get("enabled")]
        allowed=["本公司同意并确认","本公司确认并提交至分出人","本公司确认并提交至对手方","本公司确认并提交至再保人"]
        positive=[e for e in choices if e.get("name") in allowed]
        if len(positive)!=1:raise ValueError("二次确认终审决策须核对："+str([e.get("name") for e in choices]))
        await ctx.call("playwright.page_check",{"selector":positive[0]["preferred_selector"],"checked":True,"role":role})
        await ctx.call("playwright.page_fill",{"selector":"#comments","value":"仅供本地自测 "+inputs["contract_suffix"]+" 二次确认二级审核","role":role})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":role})
        await ctx.call("playwright.page_assert_url",{"url":"**/TreatyManagement/Treaty","role":role})
    final=await states()
    if final[1]["status"]!="8" or final[1]["file_status"]!="2":raise ValueError("经纪二次确认终审尚未完成，核对原提交与回调，不重复审核")
    return ctx.result(data={"platform_contract_number":inputs["platform_contract_number"],"contract_suffix":inputs["contract_suffix"],"participants":final,"secondary_confirmation_audit_level":2,"boundary":"本地业务Mock，三方最终状态由下一步只读核对"})
