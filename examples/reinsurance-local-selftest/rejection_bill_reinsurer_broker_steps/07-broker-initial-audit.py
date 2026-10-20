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
    tree=await query("SELECT id,statement_id,input_org_code,enter_org_code,parent_id,treaty_reinsurer_id,currency,net_balance,platform_statement_no,cedent_statement_no,biz_id,reviewer,review_level,JSON_UNQUOTE(JSON_EXTRACT(extra_info,'$.comment')) AS business_comment FROM ri_statement_normal WHERE statement_id=%s AND is_deleted='N' ORDER BY id",[inputs["statement_id"]],"本笔首次提交后的活动normal树")
    n=tree["rows"]
    expected=[(inputs["normal_id"],"000050","000053",None,10925281),(inputs["downstream_normal_id"],"000053","000045",inputs["normal_id"],10925282)]
    if tree["row_count"]!=2 or [(x["id"],x["input_org_code"],x["enter_org_code"],x["parent_id"],x["treaty_reinsurer_id"]) for x in n]!=expected:raise ValueError("本笔normal树或活动ID不符")
    if any(x["currency"]!="CNY" or str(x["net_balance"])!="70000.00" for x in n):raise ValueError("本笔金额或币种不符")
    ab=n[0]
    if ab["cedent_statement_no"]!=inputs["bill_label"]+"-TOTAL" or ab["biz_id"]!=inputs["expected_biz_id"] or ab["business_comment"]!=inputs["v1_comment"]:raise ValueError("本笔AB标识、业务ID或实际V1备注不符")
    if not ab["platform_statement_no"] or any(not(c.isalnum() or c=='-') for c in ab["platform_statement_no"]):raise ValueError("本笔AB平台编号缺失或格式异常")
    async def read_roles(final=False):
        r=await query("SELECT statement_normal_id,org_code,reinsurance_role,statement_status FROM ri_statement_normal_state WHERE statement_normal_id IN (%s,%s) AND is_deleted='N' ORDER BY statement_normal_id,org_code",[inputs["normal_id"],inputs["downstream_normal_id"]],"本笔经纪审核前后角色阶段",5)
        values=[3,5,3,3] if final else [3,1,0,0]
        expected=[(inputs["normal_id"],"000050","01",values[0]),(inputs["normal_id"],"000053","02",values[1]),(inputs["downstream_normal_id"],"000045","02",values[2]),(inputs["downstream_normal_id"],"000053","01",values[3])]
        if r["row_count"]!=4 or [(x["statement_normal_id"],x["org_code"],x["reinsurance_role"],int(x["statement_status"])) for x in r["rows"]]!=expected:raise ValueError("本笔不在约定经纪审核阶段，不重复审核")
        return r["rows"]
    async def read_items():
        r=await query("SELECT id,object_id,item_code,item_amount,item_comment,version FROM ri_statement_section_item WHERE object_type=0 AND object_id IN (%s,%s) AND is_deleted='N' ORDER BY object_id,item_code,id",[inputs["normal_id"],inputs["downstream_normal_id"]],"本笔审核期间完整科目基线",11)
        custom=[x for x in r["rows"] if x["version"]==2]
        expected=[(i,c,a,1) for i in [inputs["normal_id"],inputs["downstream_normal_id"]] for c,a in [("01","100000.00"),("02","20000.00"),("21","10000.00"),("60","0.00")]]
        original=[x for x in r["rows"] if x["version"]==1]
        if r["row_count"]!=9 or len(custom)!=1 or [(x["object_id"],x["item_code"],str(x["item_amount"]),x["version"]) for x in original]!=expected:raise ValueError("本笔审核前原科目或version2数量不符")
        x=custom[0]
        if x["id"]!=inputs["custom_item_id"] or x["object_id"]!=inputs["downstream_normal_id"] or x["item_code"]!="98" or str(x["item_amount"])!="0.00" or x["item_comment"]!=inputs["v1_item_comment"]:raise ValueError("本笔自有科目ID/归属/零金额/V1不符")
        return r["rows"]
    async def broker_jobs():
        r=await query("SELECT id,status FROM onchain_biz_job_info WHERE group_id=%s AND biz_no=%s AND job_task='TREATY_BILL_BROKER_PROCESS' AND is_deleted='N' ORDER BY id",[inputs["normal_id"],ab["platform_statement_no"]],"本笔经纪首次BC异步任务防重复",2)
        return r
    if inputs["expected_level"] not in [1,2]:raise ValueError("本笔经纪审核级次仅1或2")
    await read_roles()
    if ab["review_level"]!=inputs["expected_level"] or ab["reviewer"] not in [None,"","000053"]:raise ValueError("本笔审核级次或领取人不符，不重复审核")
    baseline=await read_items()
    if (await broker_jobs())["row_count"]:raise ValueError("本笔BC首次任务已存在，先核对原运行，不重复审核")
    snapshots=await query("SELECT id FROM t_business_back_up_data WHERE source_table=3 AND source_id IN (%s,%s) ORDER BY id",[inputs["normal_id"],inputs["downstream_normal_id"]],"首次经纪审核不得已有退回快照",2)
    if snapshots["row_count"]:raise ValueError("本笔已发生退回，不执行首次审核")
    processing_url="http://localhost:9877/ContractBill/list/aduit?id="+str(inputs["statement_id"])+"&treatyCode="+inputs["platform_treaty_no"]+"&statementNormalId="+str(inputs["normal_id"])+"&status=1&treatyReinsurerId=10925281&recordNo="+ab["platform_statement_no"]
    claim_mode="already_owned_no_claim_call"
    if ab["reviewer"]!="000053":
        claimed=await ctx.call("process.run",{"executable":"/Users/xiaojuju/Projects/company/bjs/dev-environment/imports/verify-venv/bin/python","args":["/Users/xiaojuju/Projects/company/bjs/dev-environment/test-support/claim_owned_bill_br_soap0003.py","--actor","000053","--normal-id",str(inputs["normal_id"]),"--expected-status","1","--expected-level",str(inputs["expected_level"]),"--claim"],"timeout_seconds":60,"max_output_bytes":65536})
        if claimed["exit_code"]!=0 or claimed["stdout_truncated"] or claimed["stderr_truncated"] or processing_url not in claimed["stdout"]:raise ValueError("本笔正常审核领取未明确成功，不重试")
        claim_mode="normal_authenticated_api_claim"
    owned=await query("SELECT reviewer,review_level FROM ri_statement_normal WHERE id=%s AND statement_id=%s AND is_deleted='N'",[inputs["normal_id"],inputs["statement_id"]],"本笔审核领取回读",2)
    if owned["row_count"]!=1 or owned["rows"][0]["reviewer"]!="000053" or owned["rows"][0]["review_level"]!=inputs["expected_level"]:raise ValueError("本笔审核领取/级次未落库")
    await authenticate("broker","broker","000053")
    await ctx.call("playwright.page_open",{"url":processing_url,"role":"broker"})
    await ctx.call("playwright.page_assert_url",{"url":processing_url,"role":"broker"})
    await ctx.call("playwright.page_assert_value",{"selector":"#cedentTreatyNo","value":inputs["platform_treaty_no"],"role":"broker"})
    await ctx.call("playwright.page_assert_value",{"selector":"input[id$='-10925281-platformStatementNo']","value":ab["platform_statement_no"],"role":"broker"})
    await ctx.call("playwright.page_assert_value",{"selector":"input[id$='-10925282-platformStatementNo']","value":n[1]["platform_statement_no"],"role":"broker"})
    await ctx.call("playwright.page_assert_value",{"selector":"input[id$='_itemComment']","value":inputs["v1_item_comment"],"role":"broker"})
    label="确认并提交审核" if inputs["expected_level"]==1 else "本公司确认并提交至再保人"
    decision={"kind":"label","value":label,"exact":True}
    await ctx.call("playwright.page_assert_state",{"selector":decision,"expected":{"count":1,"visible":True,"enabled":True},"role":"broker","timeout_ms":20000})
    await ctx.call("playwright.page_check",{"selector":decision,"checked":True,"role":"broker"})
    await ctx.call("playwright.page_fill",{"selector":"#comments","value":inputs["bill_label"]+" 经纪首次审核"+str(inputs["expected_level"])+" V1仅供本地自测","role":"broker"})
    await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":"broker"})
    await ctx.call("playwright.page_assert_url",{"url":"http://localhost:9877/ContractBill/list","role":"broker","timeout_ms":20000})
    wait_output=None;job=None
    if inputs["expected_level"]==2:
        waiting=await ctx.call("process.run",{"executable":"/Users/xiaojuju/Projects/company/bjs/dev-environment/imports/verify-venv/bin/python","args":["/Users/xiaojuju/Projects/company/bjs/dev-environment/test-support/wait_owned_bill_br_soap0003.py","--phase","initial-bc","--before-job","0"],"timeout_seconds":45,"max_output_bytes":65536})
        wait_output=waiting["stdout"];ctx.log("本笔BC首次上链只读等待="+wait_output)
        if waiting["exit_code"]!=0 or waiting["stdout_truncated"] or waiting["stderr_truncated"]:raise ValueError("本笔BC首次尚未完成或失败，保留原任务，不重复审核")
        jobs=await query("SELECT b.id AS parent_id,b.group_id AS parent_group,b.status AS parent_status,d.id AS detail_id,d.group_id AS detail_group,d.status AS detail_status,d.biz_no,d.onchain_business_id,d.biz_id,d.callback_result,d.onchain_times FROM onchain_biz_job_info b JOIN onchain_job_detail_info d ON d.biz_job_id=b.id AND d.is_deleted='N' WHERE b.group_id=%s AND b.biz_no=%s AND b.job_task='TREATY_BILL_BROKER_PROCESS' AND b.is_deleted='N' ORDER BY b.id,d.id",[inputs["normal_id"],ab["platform_statement_no"]],"本笔首次BC父AB/子BC及实际回调",2)
        if jobs["row_count"]!=1:raise ValueError("本笔首次BC任务不唯一")
        job=jobs["rows"][0]
        if job["parent_group"]!=inputs["normal_id"] or job["detail_group"]!=inputs["downstream_normal_id"] or job["onchain_business_id"]!=inputs["downstream_normal_id"] or job["biz_no"]!=n[1]["platform_statement_no"] or job["biz_id"]!=inputs["expected_bc_biz_id"] or job["parent_status"]!=8 or job["detail_status"]!=8 or job["callback_result"] not in ["成功","Success"] or job["onchain_times"]!=1:raise ValueError("本笔首次BC任务身份/回调/次数不符")
    elif (await broker_jobs())["row_count"]:raise ValueError("一级审核意外创建BC上链任务")
    final=await read_roles(inputs["expected_level"]==2)
    after_items=await read_items()
    if after_items!=baseline:raise ValueError("本笔审核期间完整科目基线变化，不重复审核")
    level=await query("SELECT reviewer,review_level FROM ri_statement_normal WHERE id=%s AND statement_id=%s AND is_deleted='N'",[inputs["normal_id"],inputs["statement_id"]],"本笔审核后实际级次",2)
    expected_after_level=2 if inputs["expected_level"]==1 else None
    if level["row_count"]!=1 or level["rows"][0]["review_level"]!=expected_after_level:raise ValueError("本笔审核后级次不符，不重复审核")
    return ctx.result(data={"statement_id":inputs["statement_id"],"record_no":inputs["record_no"],"bill_label":inputs["bill_label"],"platform_treaty_no":inputs["platform_treaty_no"],"normal_id":inputs["normal_id"],"downstream_normal_id":inputs["downstream_normal_id"],"source_table":3,"source_id":inputs["downstream_normal_id"],"ab_platform_no":ab["platform_statement_no"],"bc_platform_no":n[1]["platform_statement_no"],"custom_item_id":inputs["custom_item_id"],"v1_item_comment":inputs["v1_item_comment"],"role_states":final,"completed_audit_level":inputs["expected_level"],"next_audit_level":expected_after_level,"claim_mode":claim_mode,"initial_bc_job":job,"wait_output":wait_output,"items_unchanged":True,"boundary":"本笔正常UI单级经纪审核；一级进入二级，二级后BC待045确认并独立Mock回调；真实record/退回尚未验收"})
