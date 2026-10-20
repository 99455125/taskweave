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
    async def states(resubmitted=False):
        r=await query("SELECT statement_normal_id,org_code,reinsurance_role,statement_status FROM ri_statement_normal_state WHERE statement_normal_id IN (%s,%s) AND is_deleted='N' ORDER BY statement_normal_id,org_code",[inputs["normal_id"],inputs["downstream_normal_id"]],"本笔修改前后角色阶段",5)
        expected=[(inputs["normal_id"],"000050","01",3 if resubmitted else 13),(inputs["normal_id"],"000053","02",3 if resubmitted else 4),(inputs["downstream_normal_id"],"000045","02",0),(inputs["downstream_normal_id"],"000053","01",0)]
        if r["row_count"]!=4 or [(x["statement_normal_id"],x["org_code"],x["reinsurance_role"],int(x["statement_status"])) for x in r["rows"]]!=expected:raise ValueError("本笔未处于退回待修改阶段，不保存")
        return r["rows"]
    async def frozen():
        r=await query("SELECT id,is_deleted,SHA2(back_up_data,256) AS snapshot_sha256,JSON_UNQUOTE(JSON_EXTRACT(back_up_data,'$.comment')) AS frozen_comment FROM t_business_back_up_data WHERE source_table=3 AND source_id=%s ORDER BY id",[inputs["normal_id"]],"修改前后V1快照完整内容哈希",2)
        if r["row_count"]!=1:raise ValueError("V1快照数量变化")
        x=r["rows"][0]
        if x["id"]!=inputs["snapshot_id"] or x["is_deleted"]!="N" or x["snapshot_sha256"]!=inputs["snapshot_sha256"] or x["frozen_comment"]!=inputs["v1_comment"]:raise ValueError("V1快照已变化，不保存")
        return x
    async def identity(expected_comment):
        master=await query("SELECT treaty_id,record_no,comment FROM ri_statement WHERE id=%s AND input_org_code='000050' AND is_deleted='N'",[inputs["statement_id"]],"本笔原始主表归属",2)
        if master["row_count"]!=1 or master["rows"][0]["treaty_id"]!=325094 or master["rows"][0]["record_no"]!=inputs["record_no"]:raise ValueError("本笔主表归属变化")
        r=await query("SELECT id,input_org_code,enter_org_code,parent_id,treaty_reinsurer_id,currency,net_balance,platform_statement_no,cedent_statement_no,biz_id,reviewer,JSON_UNQUOTE(JSON_EXTRACT(extra_info,'$.comment')) AS business_comment FROM ri_statement_normal WHERE statement_id=%s AND is_deleted='N' ORDER BY id",[inputs["statement_id"]],"本笔实时normal业务备注")
        n=r["rows"];expected=[(inputs["normal_id"],"000050","000053",None,10925281),(inputs["downstream_normal_id"],"000053","000045",inputs["normal_id"],10925282)]
        if r["row_count"]!=2 or [(x["id"],x["input_org_code"],x["enter_org_code"],x["parent_id"],x["treaty_reinsurer_id"]) for x in n]!=expected:raise ValueError("本笔normal树变化")
        if any(x["currency"]!="CNY" or str(x["net_balance"])!="70000.00" for x in n):raise ValueError("本笔金额币种变化")
        ab=n[0]
        if ab["platform_statement_no"]!=inputs["ab_platform_no"] or ab["cedent_statement_no"]!=inputs["bill_label"]+"-TOTAL" or ab["biz_id"]!=inputs["expected_biz_id"] or ab["business_comment"]!=expected_comment:raise ValueError("本笔AB标识或实际业务备注版本不符")
        return ab
    if inputs["v2_comment"]!=inputs["v1_comment"]+" V2":raise ValueError("本轮V2备注规则不符")
    await states();await frozen();ab=await identity(inputs["v2_comment"])
    if ab["reviewer"]!="000050":raise ValueError("本笔重发必须已由分出方领取")
    async def initial_job():
        r=await query("SELECT b.id AS parent_id,b.status AS parent_status,d.id AS detail_id,d.status AS detail_status,d.biz_no,d.onchain_business_id,d.biz_id,d.callback_result FROM onchain_biz_job_info b JOIN onchain_job_detail_info d ON d.biz_job_id=b.id AND d.is_deleted='N' WHERE b.group_id=%s AND b.biz_no=%s AND b.job_task='TREATY_BILL_PROCESS' AND b.is_deleted='N' ORDER BY b.id,d.id",[inputs["statement_id"],inputs["record_no"]],"本笔同步重发前后初次异步任务不应新增",2)
        if r["row_count"]!=1:raise ValueError("本笔初次异步任务数量不符")
        j=r["rows"][0]
        if j["parent_id"]!=inputs["initial_parent_id"] or j["detail_id"]!=inputs["initial_detail_id"] or j["parent_status"]!=8 or j["detail_status"]!=8 or j["onchain_business_id"]!=inputs["normal_id"] or j["biz_no"]!=inputs["ab_platform_no"] or j["biz_id"]!=inputs["expected_biz_id"] or j["callback_result"] not in ["成功","Success"]:raise ValueError("本笔初次任务身份或终态不符")
        return j
    before_job=await initial_job()
    watermark=await query("SELECT MAX(id) AS max_id FROM t_ri_gsc_onchain_record",[],"同步重发前record水位",1)
    if watermark["row_count"]!=1:raise ValueError("record水位异常")
    processing_url="http://localhost:9877/ContractBill/list/pedding?id="+str(inputs["statement_id"])+"&treatyCode="+inputs["platform_treaty_no"]+"&statementNormalId="+str(inputs["normal_id"])+"&status=13&treatyReinsurerId=10925281&recordNo="+inputs["ab_platform_no"]
    await authenticate("cedant","cedent","000050")
    await ctx.call("playwright.page_open",{"url":processing_url,"role":"cedant"})
    await ctx.call("playwright.page_assert_url",{"url":processing_url,"role":"cedant"})
    await ctx.call("playwright.page_assert_value",{"selector":"#cedentTreatyNo","value":inputs["platform_treaty_no"],"role":"cedant"})
    await ctx.call("playwright.page_assert_value",{"selector":"input[id$='-10925281-platformStatementNo']","value":inputs["ab_platform_no"],"role":"cedant"})
    await ctx.call("playwright.page_assert_value",{"selector":"#comment","value":inputs["v2_comment"],"role":"cedant"})
    decision={"kind":"label","value":"本公司确认并提交至对手方","exact":True}
    await ctx.call("playwright.page_assert_state",{"selector":decision,"expected":{"count":1,"visible":True,"enabled":True},"role":"cedant","timeout_ms":20000})
    await ctx.call("playwright.page_check",{"selector":decision,"checked":True,"role":"cedant"})
    await ctx.call("playwright.page_assert_checked",{"selector":decision,"checked":True,"role":"cedant"})
    reason=inputs["bill_label"]+" 分出方V2同步重发 仅供本地自测"
    await ctx.call("playwright.page_fill",{"selector":"#comments","value":reason,"role":"cedant"})
    await ctx.call("playwright.page_assert_value",{"selector":"#comments","value":reason,"role":"cedant"})
    await ctx.call("playwright.page_wait",{"selector":".ant-notification-notice-success","state":"hidden","role":"cedant"})
    await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":"cedant"})
    # This transition is specific to this freshly-opened status13 page and only
    # occurs after the normal auditConfirm resolves code0. No action is replayed.
    await ctx.call("playwright.page_assert_url",{"url":"http://localhost:9877/ContractBill/list","role":"cedant","timeout_ms":20000})
    waiting=await ctx.call("process.run",{"executable":"/Users/xiaojuju/Projects/company/bjs/dev-environment/imports/verify-venv/bin/python","args":["/Users/xiaojuju/Projects/company/bjs/dev-environment/test-support/wait_owned_bill_cb_soap0002.py","--phase","resubmit","--snapshot-id",str(inputs["snapshot_id"]),"--snapshot-sha",inputs["snapshot_sha256"],"--expected-comment",inputs["v2_comment"]],"timeout_seconds":45,"max_output_bytes":65536})
    ctx.log("本笔同步重发后的只读检查="+waiting["stdout"])
    if waiting["exit_code"]!=0 or waiting["stdout_truncated"] or waiting["stderr_truncated"]:raise ValueError("本笔同步重发尚未完成或快照变化；保留原运行，不重复重发")
    live=await identity(inputs["v2_comment"]);snap=await frozen();final=await states(True);after_job=await initial_job()
    if before_job!=after_job:raise ValueError("同步重发不应改变或新建初次异步任务")
    return ctx.result(data={"statement_id":inputs["statement_id"],"normal_id":inputs["normal_id"],"downstream_normal_id":inputs["downstream_normal_id"],"record_no":inputs["record_no"],"bill_label":inputs["bill_label"],"platform_treaty_no":inputs["platform_treaty_no"],"source_table":3,"source_id":inputs["normal_id"],"snapshot_id":snap["id"],"snapshot_sha256":snap["snapshot_sha256"],"v1_comment":inputs["v1_comment"],"v2_comment":live["business_comment"],"ab_platform_no":inputs["ab_platform_no"],"expected_biz_id":inputs["expected_biz_id"],"role_states":final,"initial_job_unchanged":after_job,"resubmit_readonly_check":waiting["stdout"],"after_record_id":watermark["rows"][0]["max_id"],"resubmitted_via_normal_ui":True,"new_async_parent_created":False,"boundary":"本笔13页正常UI一次同步重发→列表及实际3/3；结合旧snapshot完整未变/实时V2/初次job未新增；初次8/8本身不是重发证据；不证明真实record"})
