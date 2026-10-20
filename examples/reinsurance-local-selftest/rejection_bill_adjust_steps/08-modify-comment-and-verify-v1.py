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
        r=await ctx.call("tidb.query",{"sql":sql,"params":params,"max_rows":limit,"title":title})
        if r["truncated"]:raise ValueError("本笔退回修改查询被截断")
        return r
    async def states():
        r=await query("SELECT statement_normal_id,org_code,reinsurance_role,statement_status FROM ri_statement_normal_state WHERE statement_normal_id IN (%s,%s) AND is_deleted='N' ORDER BY statement_normal_id,org_code",[inputs["normal_id"],inputs["downstream_normal_id"]],"本笔修改前后角色阶段",5)
        expected=[(inputs["normal_id"],"000050","01",13),(inputs["normal_id"],"000053","02",4),(inputs["downstream_normal_id"],"000045","02",0),(inputs["downstream_normal_id"],"000053","01",0)]
        if r["row_count"]!=4 or [(x["statement_normal_id"],x["org_code"],x["reinsurance_role"],int(x["statement_status"])) for x in r["rows"]]!=expected:raise ValueError("本笔未处于退回待修改阶段，不保存")
        return r["rows"]
    async def frozen():
        r=await query("SELECT id,is_deleted,SHA2(back_up_data,256) AS snapshot_sha256,JSON_UNQUOTE(JSON_EXTRACT(back_up_data,'$.comment')) AS frozen_comment FROM t_business_back_up_data WHERE source_table=3 AND source_id=%s ORDER BY id",[inputs["normal_id"]],"修改前后V1快照完整内容哈希",2)
        if r["row_count"]!=1:raise ValueError("V1快照数量变化")
        x=r["rows"][0]
        if x["id"]!=inputs["snapshot_id"] or x["is_deleted"]!="N" or x["snapshot_sha256"]!=inputs["snapshot_sha256"] or x["frozen_comment"]!=inputs["v1_comment"]:raise ValueError("V1快照已变化，不保存")
        return x
    async def identity(expected_comment):
        master=await query("SELECT treaty_id,record_no,treaty_statement_type,former_platform_statement_no,comment FROM ri_statement WHERE id=%s AND input_org_code='000050' AND is_deleted='N'",[inputs["statement_id"]],"本笔原始主表归属",2)
        if master["row_count"]!=1 or master["rows"][0]["treaty_id"]!=325094 or master["rows"][0]["record_no"] not in (None,"") or master["rows"][0]["treaty_statement_type"]!="31" or master["rows"][0]["former_platform_statement_no"]!="000050-2026PT00011-SOA0001":raise ValueError("本笔主表归属变化")
        r=await query("SELECT id,input_org_code,enter_org_code,parent_id,treaty_reinsurer_id,currency,net_balance,platform_statement_no,cedent_statement_no,biz_id,reviewer,former_statement_normal_id,JSON_UNQUOTE(JSON_EXTRACT(extra_info,'$.comment')) AS business_comment FROM ri_statement_normal WHERE statement_id=%s AND is_deleted='N' ORDER BY id",[inputs["statement_id"]],"本笔实时normal业务备注")
        n=r["rows"];expected=[(inputs["normal_id"],"000050","000053",None,10925281),(inputs["downstream_normal_id"],"000053","000045",inputs["normal_id"],10925282)]
        if r["row_count"]!=2 or [(x["id"],x["input_org_code"],x["enter_org_code"],x["parent_id"],x["treaty_reinsurer_id"]) for x in n]!=expected:raise ValueError("本笔normal树变化")
        if any(x["currency"]!="CNY" or str(x["net_balance"])!="1000.00" for x in n):raise ValueError("本笔金额币种变化")
        if [str(x["former_statement_normal_id"]) for x in n]!=["257312","257313"]:raise ValueError("31原normal引用改变")
        ab=n[0]
        ctx.log("本笔31实时AB核对="+str(ab))
        if ab["platform_statement_no"]!=inputs["ab_platform_no"] or ab["cedent_statement_no"]!=inputs["bill_label"]+"-AB" or ab["biz_id"]!=inputs["expected_biz_id"] or ab["business_comment"]!=expected_comment:raise ValueError("本笔AB标识或实际业务备注版本不符")
        return ab
    verify_only=inputs.get("verify_saved_only",False)
    if inputs["v2_comment"]!=inputs["v1_comment"]+" V2":raise ValueError("本轮只允许标识明确的V2业务备注")
    await states();await frozen()
    ab=await identity(inputs["v2_comment"] if verify_only else inputs["v1_comment"])
    processing_url="http://localhost:9877/ContractBill/list/adjustBill_pedding?id="+str(inputs["statement_id"])+"&treatyCode="+inputs["platform_treaty_no"]+"&statementNormalId="+str(inputs["normal_id"])+"&status=13&treatyReinsurerId=10925281&recordNo="+inputs["ab_platform_no"]+"&operation=pedding"
    if ab["reviewer"] not in [None,"","000050"]:raise ValueError("本笔修改任务由其他账号领取")
    claim_mode="already_owned_no_claim_call"
    if ab["reviewer"]!="000050":
        if verify_only:raise ValueError("只读恢复不能领取；必须已归000050")
        claimed=await ctx.call("process.run",{"executable":"/Users/xiaojuju/Projects/company/bjs/dev-environment/imports/verify-venv/bin/python","args":["/Users/xiaojuju/Projects/company/bjs/dev-environment/test-support/claim_owned_adjust_bill_544944.py","--actor","000050","--normal-id",str(inputs["normal_id"]),"--expected-status","13","--expected-level","none","--claim"],"timeout_seconds":60,"max_output_bytes":65536})
        if claimed["exit_code"]!=0 or claimed["stdout_truncated"] or claimed["stderr_truncated"] or processing_url not in claimed["stdout"]:raise ValueError("本笔分出方正常领取结果不符，不重试")
        claim_mode="normal_authenticated_api_claim"
    ab=await identity(inputs["v2_comment"] if verify_only else inputs["v1_comment"])
    if ab["reviewer"]!="000050":raise ValueError("分出方领取未落库")
    await authenticate("cedant","cedent","000050")
    await ctx.call("playwright.page_open",{"url":processing_url,"role":"cedant"})
    await ctx.call("playwright.page_assert_url",{"url":processing_url,"role":"cedant"})
    await ctx.call("playwright.page_assert_value",{"selector":"#cedentTreatyNo","value":inputs["platform_treaty_no"],"role":"cedant"})
    await ctx.call("playwright.page_assert_value",{"selector":"[id='10925281_platformStatementNo']","value":inputs["ab_platform_no"],"role":"cedant"})
    await ctx.call("playwright.page_assert_state",{"selector":"#comment","expected":{"count":1,"visible":True,"editable":True},"role":"cedant"})
    await ctx.call("playwright.page_assert_value",{"selector":"#comment","value":inputs["v2_comment"] if verify_only else inputs["v1_comment"],"role":"cedant"})
    if not verify_only:
        await ctx.call("playwright.page_fill",{"selector":"#comment","value":inputs["v2_comment"],"role":"cedant"})
        await ctx.call("playwright.page_press",{"selector":"#comment","key":"Tab","role":"cedant"})
        await ctx.call("playwright.page_assert_value",{"selector":"#comment","value":inputs["v2_comment"],"role":"cedant"})
        await ctx.call("playwright.page_wait",{"selector":".ant-notification-notice-success","state":"hidden","role":"cedant"})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"保 存","exact":True},"role":"cedant"})
        await ctx.call("playwright.page_wait",{"selector":".ant-notification-notice-success","state":"visible","role":"cedant"})
        # Reopen through the normal detail page after the fresh save notice;
        # never repeat save on an observational failure.
        await ctx.call("playwright.page_open",{"url":processing_url,"role":"cedant"})
    await ctx.call("playwright.page_assert_value",{"selector":"#comment","value":inputs["v2_comment"],"role":"cedant"})
    live=await identity(inputs["v2_comment"])
    snap=await frozen();final=await states()
    await authenticate("broker","broker","000053")
    view_url=processing_url.replace("/adjustBill_pedding?","/adjustBill_view?").replace("&status=13&","&status=4&").replace("&operation=pedding","&operation=view")
    await ctx.call("playwright.page_open",{"url":view_url,"role":"broker"})
    await ctx.call("playwright.page_assert_url",{"url":view_url,"role":"broker"})
    await ctx.call("playwright.page_assert_value",{"selector":"#cedentTreatyNo","value":inputs["platform_treaty_no"],"role":"broker"})
    await ctx.call("playwright.page_assert_state",{"selector":"#comment","expected":{"count":1,"editable":False},"role":"broker"})
    await ctx.call("playwright.page_assert_value",{"selector":"#comment","value":inputs["v1_comment"],"role":"broker"})
    return ctx.result(data={"statement_id":inputs["statement_id"],"normal_id":inputs["normal_id"],"downstream_normal_id":inputs["downstream_normal_id"],"record_no":None,"bill_label":inputs["bill_label"],"platform_treaty_no":inputs["platform_treaty_no"],"source_table":3,"source_id":inputs["normal_id"],"snapshot_id":snap["id"],"snapshot_sha256":snap["snapshot_sha256"],"v1_comment":inputs["v1_comment"],"v2_comment":live["business_comment"],"receiver_view_comment":inputs["v1_comment"],"ab_platform_no":inputs["ab_platform_no"],"role_states":final,"claim_mode":claim_mode,"saved_v2":True,"resubmitted":False,"verified_saved_only":verify_only,"boundary":"正常UI暂存V2；source3旧快照及经纪只读V1不变；主表备注不是normal业务备注的替代断言"})
