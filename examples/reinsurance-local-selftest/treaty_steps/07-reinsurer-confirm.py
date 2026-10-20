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
        r=await ctx.call("tidb.query",{"sql":"SELECT id,org_code,status,review_level,reviewer,file_status,broker_rate,amount,org_business_code,biz_id,is_sign FROM ri_treaty_reinsurer WHERE cedent_treaty_no=%s AND is_deleted='N' ORDER BY id","params":[inputs["platform_contract_number"]],"max_rows":10,"title":"本轮再保确认状态"})
        if r["truncated"] or [a["org_code"] for a in r["rows"]]!=["000050","000053","000045"]:raise ValueError("本轮三方数据不唯一")
        return r["rows"]
    before=await states()
    if before[2]["status"]=="3":
        await open_pending()
        await ctx.call("playwright.page_assert_url",{"url":"**/TreatyManagement/Treaty/entry?**","role":role})
        await ctx.call("playwright.page_assert_state",{"selector":"#orgBusinessCodeEntry","expected":{"count":1,"editable":True},"role":role})
        number="RE-"+inputs["contract_suffix"]
        await ctx.call("playwright.page_fill",{"selector":"#orgBusinessCodeEntry","value":number,"role":role})
        await ctx.call("playwright.page_assert_value",{"selector":"#orgBusinessCodeEntry","value":number,"role":role})
        original=await ctx.call("playwright.page_input_value",{"selector":"#orgBusinessCode","role":role})
        if original["value"]!=inputs["contract_suffix"]:raise ValueError("上游机构编号不一致")
        snapshot=await ctx.call("playwright.page_inspect",{"scope":"full_page","role":role})
        for ending,expected in [("_amount",100),("_brokerRate",inputs["broker_rate"])]:
            fields=[e for e in snapshot["elements"] if e.get("visible") and e.get("id","").endswith(ending)]
            if len(fields)!=1:raise ValueError("再保人份额或费率字段不唯一")
            value=await ctx.call("playwright.page_input_value",{"selector":fields[0]["preferred_selector"],"role":role})
            if float(value["value"].replace(",",""))!=expected:raise ValueError("再保人份额或费率不符")
        await ctx.call("playwright.page_assert_text",{"selector":"main a","text":"tw-local-treaty-demo.pdf","role":role})
        await ctx.call("playwright.page_check",{"selector":{"kind":"label","value":"本公司同意并确认","exact":True},"checked":True,"role":role})
        await ctx.call("playwright.page_fill",{"selector":"#comments","value":"仅供本地自测 "+inputs["contract_suffix"]+" 再保人确认","role":role})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":role})
        await ctx.call("playwright.page_assert_url",{"url":"**/TreatyManagement/Treaty","role":role})
    elif before[2]["status"] not in ["5","7","8"]:
        raise ValueError("再保任务状态不适合确认；核对实际机构审核或退回状态")
    final=await states()
    if final[2]["status"] not in ["5","7","8"] or final[2]["org_business_code"]!="RE-"+inputs["contract_suffix"]:
        raise ValueError("再保确认结果尚不满足回读条件，先核对原提交，不重复")
    if float(final[2]["amount"])!=1 or float(final[2]["broker_rate"])!=inputs["broker_rate"]/100 or final[2]["file_status"]!="2":
        raise ValueError("再保确认后份额、经纪费率或合同文件确认状态不符")
    return ctx.result(data={"platform_contract_number":inputs["platform_contract_number"],"contract_suffix":inputs["contract_suffix"],"participants":final,"reinsurer_review_levels":0,"decision":"本公司同意并确认","boundary":"仅本地三方确认；双签、最终完成及真实链验证由后续步骤核对"})
