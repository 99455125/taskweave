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
    async def query(sql,params,title,limit=3):
        r=await ctx.call("tidb.query",{"sql":sql,"params":params,"title":title,"max_rows":limit})
        if r["truncated"]:raise ValueError("原账单前置查询被截断")
        return r
    master=await query("SELECT id,treaty_id,record_no,statement_status,comment FROM ri_statement WHERE id=%s AND input_org_code='000050' AND is_deleted='N'",[inputs["source_statement_id"]],"修正原账单主表归属",2)
    if master["row_count"]!=1 or master["rows"][0]["treaty_id"]!=325094 or master["rows"][0]["record_no"]!="000050-2026PT00011-SOAP0001":raise ValueError("原账单主表或合约归属不符")
    original=await query("SELECT id,statement_id,input_org_code,enter_org_code,parent_id,treaty_reinsurer_id,currency,net_balance,platform_statement_no,sign_file_id,settlement_status,extra_info FROM ri_statement_normal WHERE id=%s AND statement_id=%s AND is_deleted='N'",[inputs["source_normal_id"],inputs["source_statement_id"]],"修正原AB明细、文件及结算边界",2)
    if original["row_count"]!=1:raise ValueError("修正原账单明细不唯一")
    n=original["rows"][0]
    if (n["input_org_code"],n["enter_org_code"],n["parent_id"],n["treaty_reinsurer_id"],n["currency"],str(n["net_balance"]),n["platform_statement_no"])!=("000050","000053",None,10925281,"CNY","70000.00",inputs["source_platform_no"]):raise ValueError("原AB机构、金额或编号不符")
    if not n["sign_file_id"]:raise ValueError("原账单尚未生成文件，不可发起修正")
    states=await query("SELECT org_code,reinsurance_role,statement_status FROM ri_statement_normal_state WHERE statement_normal_id=%s AND is_deleted='N' ORDER BY org_code",[inputs["source_normal_id"]],"原AB实际角色完成8",3)
    if states["row_count"]!=2 or [(x["org_code"],x["reinsurance_role"],x["statement_status"]) for x in states["rows"]]!=[("000050","01",8),("000053","02",8)]:raise ValueError("原AB角色尚未完成，不发起修正")
    existing=await query("SELECT id,record_no,statement_status,comment FROM ri_statement WHERE former_platform_statement_no=%s AND is_deleted='N' ORDER BY id",[inputs["source_platform_no"]],"原AB历史修正防重复",2)
    if existing["row_count"]:raise ValueError("原AB已有修正记录，先核对已有单及原创建run，不重复发起")
    now=await ctx.call("utility.now",{"timezone":"Asia/Shanghai"});label=inputs["name_prefix"]+now["compact"]
    if any(not(c.isalnum() or c=='-') for c in label):raise ValueError("修正标识格式异常")
    duplicate=await query("SELECT id FROM ri_statement WHERE comment=%s AND input_org_code='000050' AND is_deleted='N'",["仅供本地自测 "+label],"本轮修正唯一标识查重",2)
    if duplicate["row_count"]:raise ValueError("本轮修正标识已存在，不重复新建")
    await authenticate("cedant","cedent","000050")
    await ctx.call("playwright.page_open",{"url":"http://localhost:9877/ContractBill/list","role":"cedant"})
    advanced=".bill-search-box a:has-text('高级查询')"
    field_state=await ctx.call("playwright.page_state",{"selector":"#platformStatementNo","role":"cedant"})
    if field_state["match_count"]!=1 or field_state["visible"] is not True:
        await ctx.call("playwright.page_assert_state",{"selector":advanced,"expected":{"count":1,"visible":True,"enabled":True},"role":"cedant"})
        await ctx.call("playwright.page_click",{"selector":advanced,"role":"cedant"})
    await ctx.call("playwright.page_assert_state",{"selector":"#platformStatementNo","expected":{"count":1,"visible":True,"editable":True},"role":"cedant"})
    await ctx.call("playwright.page_fill",{"selector":"#platformStatementNo","value":inputs["source_platform_no"],"role":"cedant"})
    all_tab={"kind":"role","value":"tab","name":"全部","exact":False}
    await ctx.call("playwright.page_assert_state",{"selector":all_tab,"expected":{"count":1,"visible":True,"enabled":True},"role":"cedant"})
    await ctx.call("playwright.page_click",{"selector":all_tab,"role":"cedant"})
    search={"kind":"role","value":"button","name":"查 询","exact":True}
    await ctx.call("playwright.page_assert_state",{"selector":search,"expected":{"count":1,"visible":True,"enabled":True},"role":"cedant"})
    await ctx.call("playwright.page_click",{"selector":search,"role":"cedant"})
    row={"kind":"role","value":"row","name":inputs["source_platform_no"],"exact":False,"within":{"kind":"css","value":".bill-list-box"}}
    await ctx.call("playwright.page_assert_state",{"selector":row,"expected":{"count":1,"visible":True},"role":"cedant","timeout_ms":20000})
    adjust={"kind":"role","value":"button","name":"修正","exact":True,"within":row}
    await ctx.call("playwright.page_assert_state",{"selector":adjust,"expected":{"count":1,"visible":True,"enabled":True},"role":"cedant"})
    observed=await ctx.call("playwright.page_text",{"selector":row,"role":"cedant"})
    return ctx.result(data={"source_statement_id":inputs["source_statement_id"],"source_normal_id":inputs["source_normal_id"],"source_platform_no":inputs["source_platform_no"],"platform_treaty_no":"000050-2026PT00011","treaty_master_id":325094,"bill_label":label,"v1_comment":"仅供本地自测 "+label,"source_master":master["rows"][0],"source_normal":n,"source_states":states["rows"],"source_row":observed,"adjust_entry_observed":True,"new_adjust_created":False,"boundary":"本轮正常050中文全部账单列表观察原AB修正按钮；原主表6/角色8及结算6保持，尚未发起创建，复制范围由后续实际新单核验；原合约/账单属本地业务Mock"})
