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
        if r["truncated"]:raise ValueError("本笔账单领取前查询被截断")
        return r
    master=await query("SELECT id,treaty_id,record_no,treaty_statement_type,former_platform_statement_no,comment FROM ri_statement WHERE id=%s AND input_org_code='000050' AND is_deleted='N'",[inputs["statement_id"]],"经纪退回新账单主表归属",2)
    if master["row_count"]!=1 or master["rows"][0]["treaty_id"]!=325094 or master["rows"][0]["record_no"] not in (None,"") or master["rows"][0]["comment"]!=inputs["v1_comment"]:raise ValueError("经纪退回新账单主表归属或V1备注不符")
    if (master['rows'][0]['treaty_statement_type'],master['rows'][0]['former_platform_statement_no'])!=('31','000050-2026PT00011-SOA0001'):raise ValueError('本笔31原AB不符，不领取')
    tree=await query("SELECT id,statement_id,input_org_code,enter_org_code,parent_id,treaty_reinsurer_id,currency,net_balance,platform_statement_no,cedent_statement_no,biz_id,reviewer,former_statement_normal_id,JSON_UNQUOTE(JSON_EXTRACT(extra_info,'$.comment')) AS business_comment FROM ri_statement_normal WHERE statement_id=%s AND is_deleted='N' ORDER BY id",[inputs["statement_id"]],"本笔首次提交后的活动normal树")
    n=tree["rows"]
    expected=[(inputs["normal_id"],"000050","000053",None,10925281),(inputs["downstream_normal_id"],"000053","000045",inputs["normal_id"],10925282)]
    if tree["row_count"]!=2 or [(x["id"],x["input_org_code"],x["enter_org_code"],x["parent_id"],x["treaty_reinsurer_id"]) for x in n]!=expected:raise ValueError("本笔normal树或活动ID不符")
    if any(x["currency"]!="CNY" or str(x["net_balance"])!="1000.00" for x in n):raise ValueError("本笔金额或币种不符")
    if [str(x["former_statement_normal_id"]) for x in n]!=["257312","257313"]:raise ValueError("本笔31原normal引用不符，不领取")
    ab=n[0]
    if ab["cedent_statement_no"]!=inputs["bill_label"]+"-AB" or ab["biz_id"]!=inputs["expected_biz_id"] or ab["business_comment"]!=inputs["v2_comment"]:raise ValueError("本笔AB标识、业务ID或实际V1备注不符")
    if not ab["platform_statement_no"] or any(not(c.isalnum() or c=='-') for c in ab["platform_statement_no"]):raise ValueError("本笔AB平台编号缺失或格式异常")
    role_states=await query("SELECT statement_normal_id,org_code,reinsurance_role,statement_status FROM ri_statement_normal_state WHERE statement_normal_id IN (%s,%s) AND is_deleted='N' ORDER BY statement_normal_id,org_code",[inputs["normal_id"],inputs["downstream_normal_id"]],"本笔首次经纪待确认阶段",5)
    expected_states=[(inputs["normal_id"],"000050","01",3),(inputs["normal_id"],"000053","02",3),(inputs["downstream_normal_id"],"000045","02",0),(inputs["downstream_normal_id"],"000053","01",0)]
    if role_states["row_count"]!=4 or [(x["statement_normal_id"],x["org_code"],x["reinsurance_role"],int(x["statement_status"])) for x in role_states["rows"]]!=expected_states:raise ValueError("本笔未处于首次经纪待确认，不领取")
    if ab["reviewer"] not in [None,"","000053"]:raise ValueError("本笔已由其他账号领取")
    snapshots=await query("SELECT id,is_deleted,SHA2(back_up_data,256) AS snapshot_sha256,JSON_UNQUOTE(JSON_EXTRACT(back_up_data,'$.comment')) AS frozen_comment FROM t_business_back_up_data WHERE source_table=3 AND source_id=%s ORDER BY id",[inputs["normal_id"]],"第二次退回前仍唯一V1快照",2)
    if snapshots["row_count"]!=1:raise ValueError("本笔已二次退回或快照数量变化，停止重提")
    old=snapshots["rows"][0]
    if old["id"]!=inputs["snapshot_id"] or old["is_deleted"]!="N" or old["snapshot_sha256"]!=inputs["snapshot_sha256"] or old["frozen_comment"]!=inputs["v1_comment"]:raise ValueError("第二次退回前V1快照已变化")
    processing_url="http://localhost:9877/ContractBill/list/adjustBill_confirm?id="+str(inputs["statement_id"])+"&treatyCode="+inputs["platform_treaty_no"]+"&statementNormalId="+str(inputs["normal_id"])+"&status=3&treatyReinsurerId=10925281&recordNo="+ab["platform_statement_no"]+"&operation=confirm"
    claim_mode="already_owned_no_claim_call"
    if ab["reviewer"]!="000053":
        claimed=await ctx.call("process.run",{"executable":"/Users/xiaojuju/Projects/company/bjs/dev-environment/imports/verify-venv/bin/python","args":["/Users/xiaojuju/Projects/company/bjs/dev-environment/test-support/claim_owned_adjust_bill_544944.py","--actor","000053","--normal-id",str(inputs["normal_id"]),"--expected-status","3","--expected-level","none","--claim"],"timeout_seconds":60,"max_output_bytes":65536})
        if claimed["exit_code"]!=0 or claimed["stdout_truncated"] or claimed["stderr_truncated"] or processing_url not in claimed["stdout"]:raise ValueError("本笔第二次经纪正常领取结果不符，不重试")
        claim_mode="normal_authenticated_api_claim"
    reviewer=await query("SELECT reviewer FROM ri_statement_normal WHERE id=%s AND statement_id=%s AND is_deleted='N'",[inputs["normal_id"],inputs["statement_id"]],"二次退回前经纪领取回读",2)
    ctx.log("本笔31二次退回前领取回读="+str(reviewer))
    if reviewer["row_count"]!=1 or reviewer["rows"][0]["reviewer"]!="000053":raise ValueError("二次退回经纪领取未落库")
    await authenticate("broker","broker","000053")
    await ctx.call("playwright.page_open",{"url":processing_url,"role":"broker"})
    await ctx.call("playwright.page_assert_text",{"selector":"body","text":"用户名称000053","role":"broker"})
    await ctx.call("playwright.page_assert_url",{"url":processing_url,"role":"broker"})
    await ctx.call("playwright.page_assert_value",{"selector":"#cedentTreatyNo","value":inputs["platform_treaty_no"],"role":"broker"})
    await ctx.call("playwright.page_assert_value",{"selector":"[id='10925281_platformStatementNo']","value":ab["platform_statement_no"],"role":"broker"})
    await ctx.call("playwright.page_assert_value",{"selector":"#comment","value":inputs["v2_comment"],"role":"broker"})
    decision={"kind":"label","value":"退回至分出人","exact":True}
    await ctx.call("playwright.page_assert_state",{"selector":decision,"expected":{"count":1,"visible":True,"enabled":True},"role":"broker","timeout_ms":20000})
    await ctx.call("playwright.page_check",{"selector":decision,"checked":True,"role":"broker"})
    await ctx.call("playwright.page_assert_checked",{"selector":decision,"checked":True,"role":"broker"})
    reason=inputs["bill_label"]+" 经纪退回分出人 V2 仅供本地自测"
    await ctx.call("playwright.page_fill",{"selector":"#comments","value":reason,"role":"broker"})
    await ctx.call("playwright.page_assert_value",{"selector":"#comments","value":reason,"role":"broker"})
    await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":"broker"})
    await ctx.call("playwright.page_assert_url",{"url":"http://localhost:9877/ContractBill/list","role":"broker","timeout_ms":20000})
    after=await query("SELECT statement_normal_id,org_code,reinsurance_role,statement_status FROM ri_statement_normal_state WHERE statement_normal_id IN (%s,%s) AND is_deleted='N' ORDER BY statement_normal_id,org_code",[inputs["normal_id"],inputs["downstream_normal_id"]],"二次31退回AB13/4及下游实际状态",5)
    expected_after=[(inputs["normal_id"],"000050","01",13),(inputs["normal_id"],"000053","02",4),(inputs["downstream_normal_id"],"000045","02",0),(inputs["downstream_normal_id"],"000053","01",0)]
    ctx.log("本笔31二次退回后实际四角色="+str(after))
    if after["row_count"]!=4 or {(x["statement_normal_id"],x["org_code"],x["reinsurance_role"]) for x in after["rows"]}!={x[:3] for x in expected_after} or [(x["statement_normal_id"],x["org_code"],x["reinsurance_role"],int(x["statement_status"])) for x in after["rows"][:2]]!=expected_after[:2]:raise ValueError("二次31退回AB13/4或四角色身份不符，保留现场，不重复退回")
    backup=await query("SELECT id,source_table,source_id,is_deleted,SHA2(back_up_data,256) AS snapshot_sha256,JSON_UNQUOTE(JSON_EXTRACT(back_up_data,'$.comment')) AS frozen_comment FROM t_business_back_up_data WHERE source_table=3 AND source_id=%s ORDER BY id",[inputs["normal_id"]],"账单第二次退回旧Y新N及V2",3)
    if backup["row_count"]!=2:raise ValueError("第二次退回快照数目异常，不重复退回")
    old,new=backup["rows"]
    if old["id"]!=inputs["snapshot_id"] or old["is_deleted"]!="Y" or old["snapshot_sha256"]!=inputs["snapshot_sha256"] or old["frozen_comment"]!=inputs["v1_comment"] or new["id"]<=old["id"] or new["is_deleted"]!="N" or not new["snapshot_sha256"] or new["snapshot_sha256"]==old["snapshot_sha256"] or new["frozen_comment"]!=inputs["v2_comment"]:raise ValueError("第二次退回旧快照逻辑删除或新V2冻结内容不符，不重复退回")
    return ctx.result(data={"statement_id":inputs["statement_id"],"record_no":None,"bill_label":inputs["bill_label"],"platform_treaty_no":inputs["platform_treaty_no"],"normal_id":inputs["normal_id"],"downstream_normal_id":inputs["downstream_normal_id"],"source_table":3,"source_id":inputs["normal_id"],"snapshot_id":new["id"],"snapshot_sha256":new["snapshot_sha256"],"snapshots":backup["rows"],"v1_comment":inputs["v1_comment"],"v2_comment":inputs["v2_comment"],"ab_platform_no":ab["platform_statement_no"],"role_states":after["rows"],"claim_mode":claim_mode,"reason":reason,"second_rejection_performed":True,"boundary":"本笔31正常中文UI第二次经纪退回分出人；旧Y新N，V2实际业务备注冻结；独立REJECT Mock；未验证真实record"})
