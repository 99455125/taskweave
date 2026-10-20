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
        r=await ctx.call("tidb.query",{"sql":"SELECT id,org_code,status,review_level,reviewer,first_operator,file_status,broker_rate,org_business_code,biz_id FROM ri_treaty_reinsurer WHERE cedent_treaty_no=%s AND is_deleted='N' ORDER BY id","params":[inputs["platform_contract_number"]],"max_rows":10,"title":"本轮经纪确认状态"})
        if r["truncated"] or [a["org_code"] for a in r["rows"]]!=["000050","000053","000045"]:raise ValueError("本轮经纪链数据不唯一")
        return r["rows"]
    before=await states()
    audit_levels=[]
    if before[1]["status"]=="3" and before[2]["status"]=="0":
        await open_pending()
        current=await ctx.call("playwright.page_inspect",{"role":role})
        if not current["url"].endswith("/entry"):raise ValueError("当前应为经纪录入页")
        broker_number="BR-"+inputs["contract_suffix"]
        await ctx.call("playwright.page_fill",{"selector":"#orgBusinessCodeEntry","value":broker_number,"role":role})
        await ctx.call("playwright.page_assert_value",{"selector":"#orgBusinessCodeEntry","value":broker_number,"role":role})
        snapshot=await ctx.call("playwright.page_inspect",{"scope":"full_page","role":role})
        amounts=[e for e in snapshot["elements"] if e.get("id", "").endswith("_amount") and e.get("visible")]
        rates=[e for e in snapshot["elements"] if e.get("id", "").endswith("_brokerRate") and e.get("editable")]
        if len(amounts)!=2 or len(rates)!=1:raise ValueError("经纪录入份额/费率字段不唯一")
        for field in amounts:
            actual=await ctx.call("playwright.page_input_value",{"selector":field["preferred_selector"],"role":role})
            if float(actual["value"].replace(",",""))!=100:raise ValueError("经纪链份额应为100%")
        ctx.log("新会话已通过专用page_input_value回读两行disabled份额100%")
        await ctx.call("playwright.page_fill",{"selector":rates[0]["preferred_selector"],"value":str(inputs["broker_rate"]),"role":role})
        await ctx.call("playwright.page_press",{"selector":rates[0]["preferred_selector"],"key":"Tab","role":role})
        rate=await ctx.call("playwright.page_input_value",{"selector":rates[0]["preferred_selector"],"role":role})
        if float(rate["value"])!=float(inputs["broker_rate"]):raise ValueError("经纪费率回读不一致")
        child_id=rates[0]["id"].replace("_brokerRate","_amount")
        row={"kind":"css","value":"[id='"+child_id+"'] >> xpath=ancestor::tr[1]"}
        links={"kind":"css","value":"a","within":row}
        listed=await ctx.call("playwright.page_list",{"selector":links,"role":role})
        if listed["truncated"]:raise ValueError("下游附件列表被截断")
        if listed["total_count"]==0:
            pdf=await ctx.call("file.read",{"path":inputs["attachment_path"],"format":"base64","max_bytes":1048576})
            await ctx.call("playwright.page_upload",{"selector":{"kind":"css","value":"input[type=file]","within":row},"mode":"input","files":[{"name":"tw-local-treaty-demo.pdf","mime_type":"application/pdf","content_base64":pdf["content"]}],"role":role})
            await ctx.call("playwright.page_assert_text",{"selector":"body","text":"上传各参与方用印后的合同扫描件，请谨慎上传。","role":role})
            await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"确 定","exact":True},"role":role})
        await ctx.call("playwright.page_assert_text",{"selector":links,"text":"tw-local-treaty-demo.pdf","role":role})
        await ctx.call("playwright.page_check",{"selector":{"kind":"label","value":"确认并提交审核","exact":True},"checked":True,"role":role})
        await ctx.call("playwright.page_fill",{"selector":"#comments","value":"仅供本地自测 "+inputs["contract_suffix"]+" 经纪人确认","role":role})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":role})
        dialog={"kind":"role","value":"dialog","name":"参与方信息确认","exact":True}
        await ctx.call("playwright.page_assert_state",{"selector":dialog,"expected":{"count":1,"visible":True},"role":role})
        await ctx.call("playwright.page_assert_text",{"selector":dialog,"text":"000045-","role":role})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"确 定","exact":True,"within":dialog},"role":role})
        await ctx.call("playwright.page_assert_url",{"url":"**/TreatyManagement/Treaty","role":role})
    for level in ["1","2"]:
        rows=await states()
        if rows[1]["status"]=="5" and rows[2]["status"]=="3":break
        if rows[1]["status"]!="1":raise ValueError("经纪确认尚未进入机构审核；先核对本次提交，不重复")
        if str(rows[1]["review_level"])!=level:
            if level=="1" and str(rows[1]["review_level"])=="2":continue
            raise ValueError("机构审核级次不符合本地双级配置")
        await open_pending()
        await ctx.call("playwright.page_assert_url",{"url":"**/TreatyManagement/Treaty/audit?**","role":role})
        expected_decision="确认并提交审核" if level=="1" else "本公司确认并提交至再保人"
        await ctx.call("playwright.page_assert_state",{"selector":{"kind":"label","value":expected_decision,"exact":True},"expected":{"count":1,"enabled":True},"role":role})
        snapshot=await ctx.call("playwright.page_inspect",{"scope":"full_page","role":role})
        allowed=["确认并提交审核","本公司确认并提交至再保人","本公司确认并提交至对手方"]
        positive=[e for e in snapshot["elements"] if e.get("type")=="radio" and e.get("enabled") and e.get("name") in allowed]
        if len(positive)!=1:raise ValueError("当前审核正向决策不唯一，须核对实际页面")
        await ctx.call("playwright.page_check",{"selector":positive[0]["preferred_selector"],"checked":True,"role":role})
        await ctx.call("playwright.page_fill",{"selector":"#comments","value":"仅供本地自测 "+inputs["contract_suffix"]+" 经纪审核"+level,"role":role})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":role})
        await ctx.call("playwright.page_assert_url",{"url":"**/TreatyManagement/Treaty","role":role})
        audit_levels.append(level)
    final=await states()
    if final[1]["status"]!="5" or final[2]["status"]!="3":raise ValueError("两级审核后下游尚未进入待确认，须保留现场回读")
    if final[1]["org_business_code"]!="BR-"+inputs["contract_suffix"] or float(final[2]["broker_rate"])!=inputs["broker_rate"]/100:raise ValueError("经纪编号/费率未正确落库")
    return ctx.result(data={"platform_contract_number":inputs["platform_contract_number"],"contract_suffix":inputs["contract_suffix"],"participants":final,"audit_levels_in_this_attempt":audit_levels,"broker_review_levels_configured":2,"boundary":"本地专用业务Mock，未验证真实链节点"})
