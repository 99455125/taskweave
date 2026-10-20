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
    master=await query("SELECT id,treaty_id,record_no,comment FROM ri_statement WHERE id=%s AND input_org_code='000050' AND is_deleted='N'",[inputs["statement_id"]],"经纪退回新账单主表归属",2)
    if master["row_count"]!=1 or master["rows"][0]["treaty_id"]!=325094 or master["rows"][0]["record_no"]!=inputs["record_no"] or master["rows"][0]["comment"]!=inputs["v1_comment"]:raise ValueError("经纪退回新账单主表归属或V1备注不符")
    tree=await query("SELECT id,statement_id,input_org_code,enter_org_code,parent_id,treaty_reinsurer_id,currency,net_balance,platform_statement_no,cedent_statement_no,biz_id,parent_biz_id,reviewer,review_level,JSON_UNQUOTE(JSON_EXTRACT(extra_info,'$.comment')) AS business_comment FROM ri_statement_normal WHERE statement_id=%s AND is_deleted='N' ORDER BY id",[inputs["statement_id"]],"本笔首次提交后的活动normal树")
    n=tree["rows"]
    expected=[(inputs["normal_id"],"000050","000053",None,10925281),(inputs["downstream_normal_id"],"000053","000045",inputs["normal_id"],10925282)]
    if tree["row_count"]!=2 or [(x["id"],x["input_org_code"],x["enter_org_code"],x["parent_id"],x["treaty_reinsurer_id"]) for x in n]!=expected:raise ValueError("本笔normal树或活动ID不符")
    if any(x["currency"]!="CNY" or str(x["net_balance"])!="70000.00" for x in n):raise ValueError("本笔金额或币种不符")
    ab=n[0]
    if ab["cedent_statement_no"]!=inputs["bill_label"]+"-TOTAL" or ab["biz_id"]!=inputs["expected_biz_id"] or ab["business_comment"]!=inputs["v1_comment"]:raise ValueError("本笔AB标识、业务ID或实际V1备注不符")
    if not ab["platform_statement_no"] or any(not(c.isalnum() or c=='-') for c in ab["platform_statement_no"]):raise ValueError("本笔AB平台编号缺失或格式异常")
    bc=n[1]
    if bc["biz_id"]!=inputs["expected_bc_biz_id"] or bc["parent_biz_id"]!=inputs["expected_biz_id"]:raise ValueError("本笔BC业务或上游biz不符")
    if bc["review_level"] is not None or bc["reviewer"] not in [None,"","000045"]:raise ValueError("本笔再保待确认级次或领取人变化")
    verify_only=inputs["verify_saved_only"]
    async def check_roles():
        r=await query("SELECT statement_normal_id,org_code,reinsurance_role,statement_status FROM ri_statement_normal_state WHERE statement_normal_id IN (%s,%s) AND is_deleted='N' ORDER BY statement_normal_id,org_code",[inputs["normal_id"],inputs["downstream_normal_id"]],"本笔再保已退回经纪角色阶段",5)
        expected=[(inputs["normal_id"],"000050","01",3),(inputs["normal_id"],"000053","02",13),(inputs["downstream_normal_id"],"000045","02",4),(inputs["downstream_normal_id"],"000053","01",4)]
        if r["row_count"]!=4 or [(x["statement_normal_id"],x["org_code"],x["reinsurance_role"],int(x["statement_status"])) for x in r["rows"]]!=expected:raise ValueError("本笔不在再保退经纪阶段，不修改")
        return r["rows"]
    async def read_items():
        r=await query("SELECT id,object_id,item_code,item_amount,item_comment,version FROM ri_statement_section_item WHERE object_type=0 AND object_id IN (%s,%s) AND is_deleted='N' ORDER BY object_id,item_code,id",[inputs["normal_id"],inputs["downstream_normal_id"]],"本笔经纪修改前后完整科目",11)
        if r["row_count"]!=9:raise ValueError("本笔完整科目数量变化")
        return r["rows"]
    async def read_snapshot():
        r=await query("SELECT id,source_table,source_id,is_deleted,SHA2(back_up_data,256) AS snapshot_sha256,back_up_data FROM t_business_back_up_data WHERE source_table=3 AND source_id IN (%s,%s) ORDER BY id",[inputs["normal_id"],inputs["downstream_normal_id"]],"本笔修改前后BC冻结快照全文",2)
        if r["row_count"]!=1:raise ValueError("本笔首轮快照不唯一")
        x=r["rows"][0]
        if x["id"]!=inputs["snapshot_id"] or x["source_id"]!=inputs["downstream_normal_id"] or x["is_deleted"]!="N" or x["snapshot_sha256"]!=inputs["snapshot_sha256"]:raise ValueError("本笔首轮BC快照身份或SHA变化")
        return x
    await check_roles();frozen=await read_snapshot();before=await read_items()
    custom=[x for x in before if x["version"]==2]
    if len(custom)!=1:raise ValueError("本笔自有科目不唯一")
    custom=custom[0]
    if (not verify_only and custom["id"]!=inputs["custom_item_id"]) or custom["object_id"]!=inputs["downstream_normal_id"] or custom["item_code"]!="98" or str(custom["item_amount"])!="0.00" or custom["item_comment"]!=(inputs["v2_item_comment"] if verify_only else inputs["v1_item_comment"]):raise ValueError("本笔自有科目版本不符，不重复修改")
    if inputs["v2_item_comment"]!=inputs["bill_label"]+"-BROKER-V2":raise ValueError("本笔V2命名规则不符")
    if ab["review_level"] is not None or ab["reviewer"] not in [None,"","000053"]:raise ValueError("本笔经纪退回领取人或级次不符")
    processing_url="http://localhost:9877/ContractBill/list/pedding?id="+str(inputs["statement_id"])+"&treatyCode="+inputs["platform_treaty_no"]+"&statementNormalId="+str(inputs["normal_id"])+"&status=13&treatyReinsurerId=10925281&recordNo="+ab["platform_statement_no"]
    if verify_only and ab["reviewer"]!="000053":raise ValueError("只读恢复不领取任务，请核对原经纪归属")
    if ab["reviewer"]!="000053":
        claimed=await ctx.call("process.run",{"executable":"/Users/xiaojuju/Projects/company/bjs/dev-environment/imports/verify-venv/bin/python","args":["/Users/xiaojuju/Projects/company/bjs/dev-environment/test-support/claim_owned_bill_br_soap0003.py","--actor","000053","--normal-id",str(inputs["normal_id"]),"--expected-status","13","--expected-level","none","--claim"],"timeout_seconds":60,"max_output_bytes":65536})
        if claimed["exit_code"]!=0 or claimed["stdout_truncated"] or claimed["stderr_truncated"] or processing_url not in claimed["stdout"]:raise ValueError("本笔经纪退回正常领取不明确，不重试")
    owned=await query("SELECT reviewer,review_level FROM ri_statement_normal WHERE id=%s AND statement_id=%s AND is_deleted='N'",[inputs["normal_id"],inputs["statement_id"]],"本笔修改领取回读",2)
    if owned["row_count"]!=1 or owned["rows"][0]["reviewer"]!="000053" or owned["rows"][0]["review_level"] is not None:raise ValueError("本笔退回修改领取回读不符")
    await authenticate("broker","broker","000053")
    await ctx.call("playwright.page_open",{"url":processing_url,"role":"broker"})
    await ctx.call("playwright.page_assert_url",{"url":processing_url,"role":"broker"})
    await ctx.call("playwright.page_assert_value",{"selector":"#cedentTreatyNo","value":inputs["platform_treaty_no"],"role":"broker"})
    await ctx.call("playwright.page_assert_value",{"selector":"input[id$='-10925281-platformStatementNo']","value":ab["platform_statement_no"],"role":"broker"})
    await ctx.call("playwright.page_assert_value",{"selector":"input[id$='-10925282-platformStatementNo']","value":bc["platform_statement_no"],"role":"broker"})
    comment="input[id$='_itemComment']"
    await ctx.call("playwright.page_assert_state",{"selector":comment,"expected":{"count":1,"visible":True,"editable":True},"role":"broker"})
    if not verify_only:
        await ctx.call("playwright.page_assert_value",{"selector":comment,"value":inputs["v1_item_comment"],"role":"broker"})
        await ctx.call("playwright.page_fill",{"selector":comment,"value":inputs["v2_item_comment"],"role":"broker"})
        await ctx.call("playwright.page_press",{"selector":comment,"key":"Tab","role":"broker"})
        await ctx.call("playwright.page_assert_value",{"selector":comment,"value":inputs["v2_item_comment"],"role":"broker"})
        await ctx.call("playwright.page_wait",{"selector":".ant-notification-notice-success","state":"hidden","role":"broker"})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"保 存","exact":True},"role":"broker"})
        await ctx.call("playwright.page_wait",{"selector":".ant-notification-notice-success","state":"visible","role":"broker"})
        await ctx.call("playwright.page_open",{"url":processing_url,"role":"broker"})
        await ctx.call("playwright.page_assert_value",{"selector":comment,"value":inputs["v2_item_comment"],"role":"broker"})
    await ctx.call("playwright.page_assert_value",{"selector":comment,"value":inputs["v2_item_comment"],"role":"broker"})
    after=await read_items();v2=[x for x in after if x["version"]==2]
    expected_custom=dict(custom,item_comment=inputs["v2_item_comment"])
    expected_custom.pop("id")
    if len(v2)!=1 or {k:v for k,v in v2[0].items() if k!="id"}!=expected_custom:raise ValueError("暂存后实际V2科目不符，保留现场不重复保存")
    if v2[0]["id"]!=inputs["custom_item_id"]:
        history=await query("SELECT id,object_id,item_code,item_amount,item_comment,version,is_deleted FROM ri_statement_section_item WHERE id=%s AND object_type=0",[inputs["custom_item_id"]],"经纪保存原自有V1逻辑删除及V2新ID",2)
        if history["row_count"]!=1 or history["rows"][0]!={"id":inputs["custom_item_id"],"object_id":inputs["downstream_normal_id"],"item_code":"98","item_amount":"0.00","item_comment":inputs["v1_item_comment"],"version":2,"is_deleted":"Y"}:raise ValueError("自有科目新ID但原始V1逻辑删除证据不符")
    if [x for x in after if x["version"]==1]!=[x for x in before if x["version"]==1]:raise ValueError("本笔修改意外改变原始科目完整基线")
    if await read_snapshot()!=frozen:raise ValueError("本笔暂存改变旧快照")
    roles=await check_roles()
    balances=await query("SELECT id,net_balance FROM ri_statement_normal WHERE statement_id=%s AND is_deleted='N' ORDER BY id",[inputs["statement_id"]],"修改零金额说明净额不变",3)
    if balances["row_count"]!=2 or any(str(x["net_balance"])!="70000.00" for x in balances["rows"]):raise ValueError("本笔零金额说明修改改变净额")
    await authenticate("reinsurer","reinsurer","000045")
    view_url="http://localhost:9877/ContractBill/list/view?id="+str(inputs["statement_id"])+"&treatyCode="+inputs["platform_treaty_no"]+"&statementNormalId="+str(inputs["downstream_normal_id"])+"&status=4&treatyReinsurerId=10925282&recordNo="+bc["platform_statement_no"]
    await ctx.call("playwright.page_open",{"url":view_url,"role":"reinsurer"})
    await ctx.call("playwright.page_assert_value",{"selector":"#cedentTreatyNo","value":inputs["platform_treaty_no"],"role":"reinsurer"})
    await ctx.call("playwright.page_assert_value",{"selector":"input[id$='-10925282-platformStatementNo']","value":bc["platform_statement_no"],"role":"reinsurer"})
    await ctx.call("playwright.page_assert_state",{"selector":comment,"expected":{"count":1,"editable":False},"role":"reinsurer"})
    await ctx.call("playwright.page_assert_value",{"selector":comment,"value":inputs["v1_item_comment"],"role":"reinsurer"})
    return ctx.result(data={"statement_id":inputs["statement_id"],"normal_id":inputs["normal_id"],"downstream_normal_id":inputs["downstream_normal_id"],"record_no":inputs["record_no"],"bill_label":inputs["bill_label"],"platform_treaty_no":inputs["platform_treaty_no"],"expected_biz_id":inputs["expected_biz_id"],"expected_bc_biz_id":inputs["expected_bc_biz_id"],"source_table":3,"source_id":inputs["downstream_normal_id"],"custom_item":v2[0],"v1_item_comment":inputs["v1_item_comment"],"v2_item_comment":inputs["v2_item_comment"],"snapshot":frozen,"snapshot_id":inputs["snapshot_id"],"snapshot_sha256":inputs["snapshot_sha256"],"role_states":roles,"v2_saved":True,"receiver_still_v1":True,"verified_saved_only":verify_only,"prior_custom_item_id":inputs["custom_item_id"],"new_custom_item_id":v2[0]["id"],"original_rows_compared_across_save":not verify_only,"boundary":"正常经纪退回暂存自有V2零金额说明；完整原始科目/净额及BC旧快照不变，实际045只读页仍V1；尚未重提"})
