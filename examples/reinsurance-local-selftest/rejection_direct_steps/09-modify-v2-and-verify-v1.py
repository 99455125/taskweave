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
    number=inputs["platform_contract_number"]
    verify_only=inputs.get("verify_saved_only",False)
    async def query(sql,params,title,limit=4):
        r=await ctx.call("tidb.query",{"sql":sql,"params":params,"max_rows":limit,"title":title})
        if r["truncated"]:raise ValueError("本轮状态读取被截断")
        return r
    async def states():
        r=await query("SELECT id,org_code,from_id,status FROM ri_treaty_reinsurer WHERE cedent_treaty_no=%s AND is_deleted='N' ORDER BY id",[number],"暂存前后本轮三方状态")
        if r["row_count"]!=2 or [(x["id"],x["org_code"],x["from_id"],str(x["status"])) for x in r["rows"]]!=[(inputs["cedant_id"],"000050",None,"13"),(inputs["source_id"],"000045",inputs["cedant_id"],"4")]:raise ValueError("本轮不在退回待修改阶段，停止暂存")
        return r["rows"]
    async def snapshot():
        r=await query("SELECT id,source_table,source_id,SHA2(back_up_data,256) AS snapshot_sha256 FROM t_business_back_up_data WHERE source_table=2 AND source_id=%s AND is_deleted='N' ORDER BY id",[inputs["source_id"]],"暂存前后首次退回快照")
        if r["row_count"]!=1 or r["rows"][0]["id"]!=inputs["snapshot_id"] or r["rows"][0]["snapshot_sha256"]!=inputs["snapshot_sha256"]:raise ValueError("首次退回快照已变化，停止暂存")
        return r["rows"][0]
    async def master():
        r=await query("SELECT id,treaty_name,org_business_code FROM ri_treaty_master WHERE id=%s AND cedent_treaty_no=%s AND org_business_code=%s AND is_deleted='N'",[inputs["master_id"],number,inputs["contract_suffix"]],"本轮实时合约名称",2)
        if r["row_count"]!=1:raise ValueError("本轮主表归属变化")
        return r["rows"][0]
    async def find_card(role,for_process=False):
        await ctx.call("playwright.page_open",{"url":"http://localhost:9877/TreatyManagement/Treaty","role":role})
        await ctx.call("playwright.page_assert_state",{"selector":"#查询条件_treatyCode","expected":{"count":1,"visible":True},"role":role})
        await ctx.call("playwright.page_click",{"selector":"text=全部","role":role})
        await ctx.call("playwright.page_fill",{"selector":"#查询条件_treatyCode","value":number,"role":role})
        button={"kind":"role","value":"button","name":"查 询","exact":True}
        await ctx.call("playwright.page_assert_state",{"selector":button,"expected":{"count":1,"visible":True,"enabled":True},"role":role})
        await ctx.call("playwright.page_click",{"selector":button,"role":role})
        if for_process:
            tab={"kind":"role","value":"tab","name":"我的任务","exact":False}
            await ctx.call("playwright.page_assert_state",{"selector":tab,"expected":{"count":1,"enabled":True},"role":role})
            await ctx.call("playwright.page_click",{"selector":tab,"role":role})
        else:
            tab={"kind":"role","value":"tab","name":"全部","exact":False}
            await ctx.call("playwright.page_assert_state",{"selector":tab,"expected":{"count":1,"enabled":True},"role":role})
            await ctx.call("playwright.page_click",{"selector":tab,"role":role})
        card='div[class*="list-item_"]:has(a:text-is("平台合约编号：'+number+'"))'
        await ctx.call("playwright.page_assert_state",{"selector":card,"expected":{"count":1,"visible":True},"role":role})
        return card
    await states()
    before=await master()
    if before["treaty_name"]!=(inputs["v2_treaty_name"] if verify_only else inputs["expected_treaty_name"]):raise ValueError("暂存前实时名称不是预期版本，不覆盖")
    await snapshot()
    await authenticate("cedant","cedent","000050")
    card=await find_card("cedant",True)
    await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"处 理","exact":True,"within":{"kind":"css","value":card}},"role":"cedant"})
    await ctx.call("playwright.page_assert_url",{"url":"**/TreatyManagement/Treaty/cendentrollback?**cedentTreatyNo="+number+"&**id="+str(inputs["cedant_id"])+"&**","role":"cedant"})
    await ctx.call("playwright.page_assert_value",{"selector":"#orgBusinessCode","value":inputs["contract_suffix"],"role":"cedant"})
    await ctx.call("playwright.page_assert_state",{"selector":"#treatyName","expected":{"count":1,"editable":True},"role":"cedant"})
    if not verify_only:
        await ctx.call("playwright.page_assert_value",{"selector":"#treatyName","value":inputs["contract_suffix"],"role":"cedant"})
        await ctx.call("playwright.page_fill",{"selector":"#treatyName","value":inputs["v2_input_suffix"],"role":"cedant"})
        await ctx.call("playwright.page_press",{"selector":"#treatyName","key":"Tab","role":"cedant"})
        await ctx.call("playwright.page_assert_value",{"selector":"#treatyName","value":inputs["v2_input_suffix"],"role":"cedant"})
        await ctx.call("playwright.page_wait",{"selector":".ant-notification-notice-success","state":"hidden","role":"cedant"})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"保 存","exact":True},"role":"cedant"})
        await ctx.call("playwright.page_wait",{"selector":".ant-notification-notice-success","state":"visible","role":"cedant"})
    after=await master()
    if after["treaty_name"]!=inputs["v2_treaty_name"]:raise ValueError("暂存后未读到V2；先核对结果，不重复保存")
    unchanged=await snapshot()
    await authenticate("reinsurer","reinsurer","000045")
    card=await find_card("reinsurer")
    link={"kind":"css","value":'a:text-is("平台合约编号：'+number+'")',"within":{"kind":"css","value":card}}
    await ctx.call("playwright.page_assert_state",{"selector":link,"expected":{"count":1,"visible":True},"role":"reinsurer"})
    await ctx.call("playwright.page_click",{"selector":link,"role":"reinsurer"})
    await ctx.call("playwright.page_assert_url",{"url":"**/TreatyManagement/Treaty/view?**cedentTreatyNo="+number+"&**id="+str(inputs["source_id"])+"&**","role":"reinsurer"})
    await ctx.call("playwright.page_assert_state",{"selector":"#treatyName","expected":{"count":1,"editable":False},"role":"reinsurer"})
    candidate=await ctx.call("playwright.page_input_value",{"selector":"#treatyName","role":"reinsurer"})
    ctx.log("再保人退回只读详情初次名称采样="+candidate["value"])
    await ctx.call("playwright.page_assert_value",{"selector":"#treatyName","value":inputs["contract_suffix"],"role":"reinsurer"})
    readonly=await ctx.call("playwright.page_input_value",{"selector":"#treatyName","role":"reinsurer"})
    if readonly["value"]!=inputs["contract_suffix"]:raise ValueError("再保人退回只读详情未保持V1，可能泄漏实时V2")
    final=await states()
    return ctx.result(data={"platform_contract_number":number,"contract_suffix":inputs["contract_suffix"],"source_table":2,"source_id":inputs["source_id"],"snapshot":unchanged,"v1_treaty_name":inputs["expected_treaty_name"],"v2_treaty_name":after["treaty_name"],"receiver_view_suffix":readonly["value"],"participants":final,"verified_saved_only":verify_only,"saved_v2":True,"receiver_view_still_v1":True,"resubmitted":False})
