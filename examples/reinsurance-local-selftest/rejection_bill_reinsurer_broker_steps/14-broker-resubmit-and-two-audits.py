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
    async def roles(expected_values):
        r=await query("SELECT statement_normal_id,org_code,reinsurance_role,statement_status FROM ri_statement_normal_state WHERE statement_normal_id IN (%s,%s) AND is_deleted='N' ORDER BY statement_normal_id,org_code",[inputs["normal_id"],inputs["downstream_normal_id"]],"经纪重提及双级审核角色阶段",5)
        expected=[(inputs["normal_id"],"000050","01",expected_values[0]),(inputs["normal_id"],"000053","02",expected_values[1]),(inputs["downstream_normal_id"],"000045","02",expected_values[2]),(inputs["downstream_normal_id"],"000053","01",expected_values[3])]
        if r["row_count"]!=4 or [(x["statement_normal_id"],x["org_code"],x["reinsurance_role"],int(x["statement_status"])) for x in r["rows"]]!=expected:raise ValueError("本笔不在声明重提/审核阶段，不重复提交")
        return r["rows"]
    async def items():
        r=await query("SELECT id,object_id,item_code,item_amount,item_comment,version FROM ri_statement_section_item WHERE object_type=0 AND object_id IN (%s,%s) AND is_deleted='N' ORDER BY object_id,item_code,id",[inputs["normal_id"],inputs["downstream_normal_id"]],"本笔重提V2完整科目",11)
        original=[x for x in r["rows"] if x["version"]==1];custom=[x for x in r["rows"] if x["version"]==2]
        expected=[(i,c,a,1) for i in [inputs["normal_id"],inputs["downstream_normal_id"]] for c,a in [("01","100000.00"),("02","20000.00"),("21","10000.00"),("60","0.00")]]
        if r["row_count"]!=9 or len(custom)!=1 or [(x["object_id"],x["item_code"],str(x["item_amount"]),x["version"]) for x in original]!=expected:raise ValueError("本笔重提原始科目或自有行数不符")
        c=custom[0]
        if c["object_id"]!=inputs["downstream_normal_id"] or c["item_code"]!="98" or str(c["item_amount"])!="0.00" or c["item_comment"]!=inputs["v2_item_comment"]:raise ValueError("本笔重提实际V2零科目不符")
        return r["rows"]
    async def snapshot_guard():
        r=await query("SELECT id,source_id,is_deleted,SHA2(back_up_data,256) AS snapshot_sha256 FROM t_business_back_up_data WHERE source_table=3 AND source_id IN (%s,%s) ORDER BY id",[inputs["normal_id"],inputs["downstream_normal_id"]],"经纪重提首轮BC快照保持",2)
        if r["row_count"]!=1 or r["rows"][0]!={"id":inputs["snapshot_id"],"source_id":inputs["downstream_normal_id"],"is_deleted":"N","snapshot_sha256":inputs["snapshot_sha256"]}:raise ValueError("本笔重提原BC快照变化")
    async def jobs():
        r=await query("SELECT b.id AS parent_id,b.group_id AS parent_group,b.status AS parent_status,d.id AS detail_id,d.group_id AS detail_group,d.status AS detail_status,d.biz_no,d.onchain_business_id,d.biz_id,d.callback_result,d.onchain_times FROM onchain_biz_job_info b JOIN onchain_job_detail_info d ON d.biz_job_id=b.id AND d.is_deleted='N' WHERE b.group_id=%s AND b.biz_no=%s AND b.job_task='TREATY_BILL_BROKER_PROCESS' AND b.is_deleted='N' ORDER BY b.id,d.id",[inputs["normal_id"],ab["platform_statement_no"]],"本笔重提独立BC异步任务",3)
        for j in r["rows"]:
            if j["parent_group"]!=inputs["normal_id"] or j["detail_group"]!=inputs["downstream_normal_id"] or j["onchain_business_id"]!=inputs["downstream_normal_id"] or j["biz_no"]!=bc["platform_statement_no"] or j["biz_id"]!=inputs["expected_bc_biz_id"] or j["parent_status"]!=8 or j["detail_status"]!=8 or j["callback_result"] not in ["成功","Success"] or j["onchain_times"]!=1:raise ValueError("本笔BC任务归属/回调/次数异常")
        return r["rows"]
    phase=inputs["resume_phase"]
    if phase not in [0,1,2]:raise ValueError("本笔重提阶段参数不合法")
    await roles([3,13,4,4] if phase==0 else [3,1,4,4]);await snapshot_guard();baseline=await items()
    prior=await jobs()
    if len(prior)!=1 or prior[0]["parent_id"]!=inputs["initial_bc_parent_id"]:raise ValueError("本笔BC重提已有新任务或首轮水位不符，不重复提交")
    expected_level=None if phase==0 else phase
    if ab["review_level"]!=expected_level or ab["reviewer"] not in [None,"","000053"]:raise ValueError("本笔声明阶段与实际经纪审核级次不符")
    await authenticate("broker","broker","000053")
    completed=[]
    for stage in range(phase,3):
        level=None if stage==0 else stage;status=13 if stage==0 else 1
        await roles([3,13,4,4] if stage==0 else [3,1,4,4]);await snapshot_guard()
        own=await query("SELECT reviewer,review_level FROM ri_statement_normal WHERE id=%s AND statement_id=%s AND is_deleted='N'",[inputs["normal_id"],inputs["statement_id"]],"经纪重提每级前归属级次",2)
        if own["row_count"]!=1 or own["rows"][0]["review_level"]!=level or own["rows"][0]["reviewer"] not in [None,"","000053"]:raise ValueError("本笔重提每级实际级次不符")
        url="http://localhost:9877/ContractBill/list/"+("pedding" if stage==0 else "aduit")+"?id="+str(inputs["statement_id"])+"&treatyCode="+inputs["platform_treaty_no"]+"&statementNormalId="+str(inputs["normal_id"])+"&status="+str(status)+"&treatyReinsurerId=10925281&recordNo="+ab["platform_statement_no"]
        if own["rows"][0]["reviewer"]!="000053":
            claimed=await ctx.call("process.run",{"executable":"/Users/xiaojuju/Projects/company/bjs/dev-environment/imports/verify-venv/bin/python","args":["/Users/xiaojuju/Projects/company/bjs/dev-environment/test-support/claim_owned_bill_br_soap0003.py","--actor","000053","--normal-id",str(inputs["normal_id"]),"--expected-status",str(status),"--expected-level","none" if level is None else str(level),"--claim"],"timeout_seconds":60,"max_output_bytes":65536})
            if claimed["exit_code"]!=0 or claimed["stdout_truncated"] or claimed["stderr_truncated"] or url not in claimed["stdout"]:raise ValueError("本笔经纪重提正常领取未明确成功，不重试")
        owned=await query("SELECT reviewer,review_level FROM ri_statement_normal WHERE id=%s AND statement_id=%s AND is_deleted='N'",[inputs["normal_id"],inputs["statement_id"]],"经纪重提领取回读",2)
        if owned["row_count"]!=1 or owned["rows"][0]!={"reviewer":"000053","review_level":level}:raise ValueError("本笔经纪重提领取未落库")
        await ctx.call("playwright.page_open",{"url":url,"role":"broker"})
        await ctx.call("playwright.page_assert_url",{"url":url,"role":"broker"})
        await ctx.call("playwright.page_assert_value",{"selector":"#cedentTreatyNo","value":inputs["platform_treaty_no"],"role":"broker"})
        for party,norm in [(10925281,ab),(10925282,bc)]:
            await ctx.call("playwright.page_assert_value",{"selector":"input[id$='-"+str(party)+"-platformStatementNo']","value":norm["platform_statement_no"],"role":"broker"})
        await ctx.call("playwright.page_assert_value",{"selector":"input[id$='_itemComment']","value":inputs["v2_item_comment"],"role":"broker"})
        decision={"kind":"label","value":"本公司确认并提交至再保人" if stage==2 else "确认并提交审核","exact":True}
        await ctx.call("playwright.page_assert_state",{"selector":decision,"expected":{"count":1,"visible":True,"enabled":True},"role":"broker","timeout_ms":20000})
        await ctx.call("playwright.page_check",{"selector":decision,"checked":True,"role":"broker"})
        await ctx.call("playwright.page_fill",{"selector":"#comments","value":inputs["bill_label"]+" 经纪V2重提阶段"+str(stage)+" 仅供本地自测","role":"broker"})
        # BJS AntiRepeat expires after 5 seconds per master/current user.
        # Explicit business throttle, independent of locator readiness; never retry submit.
        cooldown=await ctx.call("process.run",{"executable":"/bin/sleep","args":["6"],"timeout_seconds":10,"max_output_bytes":1024})
        if cooldown["exit_code"]!=0 or cooldown["stdout_truncated"] or cooldown["stderr_truncated"]:raise ValueError("本笔5秒业务防重间隔未完成，不提交")
        await roles([3,13,4,4] if stage==0 else [3,1,4,4])
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":"broker"})
        await ctx.call("playwright.page_assert_url",{"url":"http://localhost:9877/ContractBill/list","role":"broker","timeout_ms":20000})
        if stage<2:
            await roles([3,1,4,4])
            after_level=await query("SELECT review_level FROM ri_statement_normal WHERE id=%s AND statement_id=%s AND is_deleted='N'",[inputs["normal_id"],inputs["statement_id"]],"经纪重提后审核级次",2)
            if after_level["row_count"]!=1 or after_level["rows"][0]["review_level"]!=stage+1:raise ValueError("本笔经纪重提后审核级次不符，不重复提交")
            if await jobs()!=prior:raise ValueError("本笔未到末级却新增BC任务")
        current=await items()
        if [x for x in current if x["version"]==1]!=[x for x in baseline if x["version"]==1]:raise ValueError("本笔重提改变原始完整科目基线")
        if stage>0 and current!=baseline:raise ValueError("本笔双级审核改变V2完整科目")
        baseline=current;completed.append(stage);ctx.log("本笔经纪V2重提完成阶段="+str(stage));await snapshot_guard()
    waiting=await ctx.call("process.run",{"executable":"/Users/xiaojuju/Projects/company/bjs/dev-environment/imports/verify-venv/bin/python","args":["/Users/xiaojuju/Projects/company/bjs/dev-environment/test-support/wait_owned_bill_br_soap0003.py","--phase","resubmit-bc","--before-job",str(inputs["initial_bc_parent_id"])],"timeout_seconds":45,"max_output_bytes":65536})
    ctx.log("本笔BC重提只读等待="+waiting["stdout"])
    if waiting["exit_code"]!=0 or waiting["stdout_truncated"] or waiting["stderr_truncated"]:raise ValueError("本笔重提BC未明确回调成功，不重复提交")
    current_jobs=await jobs()
    if len(current_jobs)!=2 or current_jobs[0]!=prior[0] or current_jobs[1]["parent_id"]<=inputs["initial_bc_parent_id"]:raise ValueError("本笔重提应唯一新BC父任务且旧父不变")
    final=await roles([3,5,3,3]);await snapshot_guard()
    return ctx.result(data={"statement_id":inputs["statement_id"],"normal_id":inputs["normal_id"],"downstream_normal_id":inputs["downstream_normal_id"],"record_no":inputs["record_no"],"bill_label":inputs["bill_label"],"platform_treaty_no":inputs["platform_treaty_no"],"expected_biz_id":inputs["expected_biz_id"],"expected_bc_biz_id":inputs["expected_bc_biz_id"],"v1_comment":inputs["v1_comment"],"v1_item_comment":inputs["v1_item_comment"],"v2_item_comment":inputs["v2_item_comment"],"source_table":3,"source_id":inputs["downstream_normal_id"],"snapshot_id":inputs["snapshot_id"],"snapshot_sha256":inputs["snapshot_sha256"],"custom_item":[x for x in baseline if x["version"]==2][0],"completed_stages":completed,"resume_phase":phase,"role_states":final,"initial_bc_job":prior[0],"resubmit_bc_job":current_jobs[1],"wait_output":waiting["stdout"],"old_snapshot_unchanged":True,"boundary":"经纪V2正常UI重提和双级审核，新独立BC父明细8/8真实Mock回调；源3旧BC快照保持；未执行二次退回或真实record"})
