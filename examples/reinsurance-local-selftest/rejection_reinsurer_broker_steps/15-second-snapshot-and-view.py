async def run(ctx, inputs):
    async def authenticate(role, account_key, expected_account):
        # Existing local credentials stay outside portable task packages and outputs.
        credentials = await ctx.call("file.read", {
            "path": inputs["credentials_path"], "format": "json", "max_bytes": 65536
        })
        ui = credentials["content"]["ui"]
        if ui["url"] != "http://localhost:9877/login":
            raise ValueError("凭据仅允许用于交接指定的本地登录地址")
        account = ui["accounts"][account_key]
        if account != expected_account or not ui["sharedPassword"]:
            raise ValueError("交接账号或已有密码不完整")
        current=await ctx.call("playwright.page_inspect",{"role":role})
        if current["url"].startswith("http://localhost:9877/") and not current["url"].endswith("/login"):
            await ctx.call("playwright.page_assert_text",{"selector":"body","text":"用户名称"+account,"role":role})
            await ctx.call("playwright.page_assert_text",{"selector":"body","text":"中文","role":role})
            return
        await ctx.call("playwright.page_open", {"url": ui["url"], "role": role})
        await ctx.call("playwright.page_assert_state", {
            "selector": "#username", "expected": {"count": 1, "visible": True}, "role": role
        })
        placeholder=await ctx.call("playwright.page_attribute",{"selector":"#username","name":"placeholder","role":role})
        if placeholder["value"]!="请输入用户名":
            await ctx.call("playwright.page_click",{"selector":"#root > div:nth-of-type(1) > div:nth-of-type(3) > div:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(1) > form:nth-of-type(1) > div:nth-of-type(4) > div:nth-of-type(1) > div:nth-of-type(1)","role":role})
            option={"kind":"role","value":"option","name":"中文","exact":True}
            await ctx.call("playwright.page_assert_state",{"selector":option,"expected":{"count":1,"visible":True},"role":role})
            await ctx.call("playwright.page_click",{"selector":option,"role":role})
        placeholder=await ctx.call("playwright.page_attribute",{"selector":"#username","name":"placeholder","role":role})
        if placeholder["value"]!="请输入用户名":raise ValueError("登录页尚未切换中文")
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
    result=await ctx.call("tidb.query",{"sql":"SELECT id,source_table,source_id,SHA2(back_up_data,256) AS snapshot_sha256,JSON_UNQUOTE(JSON_EXTRACT(back_up_data,'$.riTreatyMasterDTO.treatyName')) AS frozen_name,JSON_UNQUOTE(JSON_EXTRACT(back_up_data,'$.riTreatyMasterDTO.cedentTreatyNo')) AS frozen_number,JSON_UNQUOTE(JSON_EXTRACT(back_up_data,'$.currentTreatyReinsurer.id')) AS frozen_party_id,JSON_UNQUOTE(JSON_EXTRACT(back_up_data,'$.currentTreatyReinsurer.brokerRate')) AS frozen_rate FROM t_business_back_up_data WHERE source_table=%s AND source_id=%s AND is_deleted='N' ORDER BY id","params":[inputs["source_table"],inputs["source_id"]],"max_rows":2,"title":"第二次退回唯一有效V2快照及内容"})
    if result["truncated"] or result["row_count"]!=1:raise ValueError("二次退回有效快照不唯一")
    row=result["rows"][0]
    if row["id"]!=inputs["expected_snapshot_id"] or row["snapshot_sha256"]!=inputs["expected_snapshot_sha256"] or row["frozen_name"]!=inputs["expected_treaty_name"] or row["frozen_number"]!=inputs["platform_contract_number"]:raise ValueError("二次退回V2快照归属或内容不符")
    if str(row["frozen_party_id"])!=str(inputs["source_id"]) or abs(float(row["frozen_rate"])-inputs["v2_broker_rate"])>0.000001:raise ValueError("V2快照参与方或费率不符")
    party=await ctx.call("tidb.query",{"sql":"SELECT id,org_code,from_id,status,biz_id FROM ri_treaty_reinsurer WHERE id=%s AND cedent_treaty_no=%s AND is_deleted='N'","params":[inputs["source_id"],inputs["platform_contract_number"]],"max_rows":2,"title":"再保人退回详情任务状态与归属"})
    if party["truncated"] or party["row_count"]!=1 or party["rows"][0]["org_code"]!="000045" or party["rows"][0]["from_id"]!=inputs["broker_id"] or str(party["rows"][0]["status"])!="4" or party["rows"][0]["biz_id"]!=inputs["expected_biz_id"]:raise ValueError("当前不在本轮再保人退回详情阶段")
    await authenticate("reinsurer","reinsurer","000045")
    await ctx.call("playwright.page_assert_text",{"selector":"body","text":"用户名称000045","role":"reinsurer"})
    await ctx.call("playwright.page_open",{"url":"http://localhost:9877/TreatyManagement/Treaty","role":"reinsurer"})
    await ctx.call("playwright.page_assert_state",{"selector":"#查询条件_treatyCode","expected":{"count":1,"visible":True},"role":"reinsurer"})
    await ctx.call("playwright.page_fill",{"selector":"#查询条件_treatyCode","value":inputs["platform_contract_number"],"role":"reinsurer"})
    button={"kind":"role","value":"button","name":"查 询","exact":True}
    await ctx.call("playwright.page_assert_state",{"selector":button,"expected":{"count":1,"enabled":True},"role":"reinsurer"})
    await ctx.call("playwright.page_click",{"selector":button,"role":"reinsurer"})
    tab={"kind":"role","value":"tab","name":"全部","exact":False}
    await ctx.call("playwright.page_assert_state",{"selector":tab,"expected":{"count":1,"enabled":True},"role":"reinsurer"})
    await ctx.call("playwright.page_click",{"selector":tab,"role":"reinsurer"})
    card='div[class*="list-item_"]:has(a:text-is("平台合约编号：'+inputs["platform_contract_number"]+'"))'
    await ctx.call("playwright.page_assert_state",{"selector":card,"expected":{"count":1,"visible":True},"role":"reinsurer"})
    link={"kind":"css","value":'a:text-is("平台合约编号：'+inputs["platform_contract_number"]+'")',"within":{"kind":"css","value":card}}
    await ctx.call("playwright.page_assert_state",{"selector":link,"expected":{"count":1,"visible":True},"role":"reinsurer"})
    await ctx.call("playwright.page_click",{"selector":link,"role":"reinsurer"})
    await ctx.call("playwright.page_assert_url",{"url":"**/TreatyManagement/Treaty/view?**cedentTreatyNo="+inputs["platform_contract_number"]+"&**id="+str(inputs["source_id"])+"&**","role":"reinsurer"})
    await ctx.call("playwright.page_assert_value",{"selector":"#treatyName","value":inputs["contract_suffix"],"role":"reinsurer"})
    await ctx.call("playwright.page_assert_state",{"selector":"#treatyName","expected":{"count":1,"editable":False},"role":"reinsurer"})
    value=await ctx.call("playwright.page_input_value",{"selector":"#treatyName","role":"reinsurer"})
    await ctx.call("playwright.page_assert_state",{"selector":"input[id$='_brokerRate']","expected":{"count":1,"visible":True,"editable":False},"role":"reinsurer"})
    rate=await ctx.call("playwright.page_input_value",{"selector":"input[id$='_brokerRate']","role":"reinsurer"})
    shown=float(rate["value"].replace(",",""))
    if abs(shown-inputs["v2_broker_rate"])>0.000001:raise ValueError("二次退回只读详情费率并非V2")
    return ctx.result(data={"snapshot_id":row["id"],"snapshot_sha256":row["snapshot_sha256"],"source_table":row["source_table"],"source_id":row["source_id"],"platform_contract_number":inputs["platform_contract_number"],"frozen_name":row["frozen_name"],"frozen_broker_rate_percent":float(row["frozen_rate"]),"receiver_view_broker_rate_percent":shown,"receiver_view_suffix":value["value"],"second_version_readonly_view_verified":True,"boundary":"本轮独立再保人退回流程分段完成；真实record与全新会话整套运行未验证"})
