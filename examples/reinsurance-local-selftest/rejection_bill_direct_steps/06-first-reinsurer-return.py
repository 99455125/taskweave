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
    master=await query("SELECT id,treaty_id,record_no,comment FROM ri_statement WHERE id=%s AND input_org_code='000050' AND is_deleted='N'",[inputs["statement_id"]],"直连退回新账单主表归属",2)
    if master["row_count"]!=1 or master["rows"][0]["treaty_id"]!=317093 or master["rows"][0]["record_no"]!=inputs["record_no"] or master["rows"][0]["comment"]!=inputs["v1_comment"]:raise ValueError("直连退回新账单主表归属或V1备注不符")
    tree=await query("SELECT id,statement_id,input_org_code,enter_org_code,parent_id,treaty_reinsurer_id,currency,net_balance,platform_statement_no,cedent_statement_no,biz_id,reviewer,review_level,JSON_UNQUOTE(JSON_EXTRACT(extra_info,'$.comment')) AS business_comment FROM ri_statement_normal WHERE statement_id=%s AND is_deleted='N' ORDER BY id",[inputs["statement_id"]],"本笔首次提交后的活动normal树")
    n=tree["rows"]
    expected=[(inputs["normal_id"],"000050","000045",None,10947283)]
    if tree["row_count"]!=1 or [(x["id"],x["input_org_code"],x["enter_org_code"],x["parent_id"],x["treaty_reinsurer_id"]) for x in n]!=expected:raise ValueError("本笔normal树或活动ID不符")
    if any(x["currency"]!="CNY" or str(x["net_balance"])!="14000.00" for x in n):raise ValueError("本笔金额或币种不符")
    ab=n[0]
    if ab["cedent_statement_no"]!=inputs["bill_label"]+"-TOTAL" or ab["biz_id"]!=inputs["expected_biz_id"] or ab["business_comment"]!=inputs["v1_comment"]:raise ValueError("本笔AB标识、业务ID或实际V1备注不符")
    if not ab["platform_statement_no"] or any(not(c.isalnum() or c=='-') for c in ab["platform_statement_no"]):raise ValueError("本笔AB平台编号缺失或格式异常")
    role_states=await query("SELECT statement_normal_id,org_code,reinsurance_role,statement_status FROM ri_statement_normal_state WHERE statement_normal_id=%s AND is_deleted='N' ORDER BY statement_normal_id,org_code",[inputs["normal_id"]],"本笔首次直连再保待确认阶段",5)
    expected_states=[(inputs["normal_id"],"000045","02",3),(inputs["normal_id"],"000050","01",3)]
    if role_states["row_count"]!=2 or [(x["statement_normal_id"],x["org_code"],x["reinsurance_role"],int(x["statement_status"])) for x in role_states["rows"]]!=expected_states:raise ValueError("本笔未处于首次直连再保待确认，不领取")
    if ab["review_level"] is not None:raise ValueError("本笔直连再保待确认不应有审核级次")
    if ab["reviewer"] not in [None,"","000045"]:raise ValueError("本笔已由其他账号领取")
    snapshots=await query("SELECT id,is_deleted FROM t_business_back_up_data WHERE source_table=3 AND source_id=%s ORDER BY id",[inputs["normal_id"]],"首次账单退回前快照防重",2)
    if snapshots["row_count"]:raise ValueError("本笔已存在退回快照，先核对原运行")
    jobs=await query("SELECT b.id AS parent_id,b.group_id AS parent_group,b.status AS parent_status,d.id AS detail_id,d.group_id AS detail_group,d.status AS detail_status,d.biz_no,d.onchain_business_id,d.biz_id,d.callback_result,d.onchain_times FROM onchain_biz_job_info b JOIN onchain_job_detail_info d ON d.biz_job_id=b.id AND d.is_deleted='N' WHERE b.group_id=%s AND b.biz_no=%s AND b.job_task='TREATY_BILL_PROCESS' AND b.is_deleted='N' ORDER BY b.id,d.id",[inputs["statement_id"],inputs["record_no"]],"本笔唯一初始直连任务",2)
    if jobs["row_count"]!=1:raise ValueError("本笔初始直连任务不唯一")
    job=jobs["rows"][0]
    if job["parent_id"]!=inputs["initial_parent_id"] or job["detail_id"]!=inputs["initial_detail_id"] or job["parent_group"]!=inputs["statement_id"] or job["detail_group"]!=inputs["statement_id"] or job["onchain_business_id"]!=inputs["normal_id"] or job["biz_no"]!=ab["platform_statement_no"] or job["biz_id"]!=inputs["expected_biz_id"] or job["parent_status"]!=8 or job["detail_status"]!=8 or job["callback_result"] not in ["成功","Success"] or job["onchain_times"]!=1:raise ValueError("本笔初始直连任务归属或终态不符")
    processing_url="http://localhost:9877/ContractBill/list/confirm?id="+str(inputs["statement_id"])+"&treatyCode="+inputs["platform_treaty_no"]+"&statementNormalId="+str(inputs["normal_id"])+"&status=3&treatyReinsurerId=10947283&recordNo="+ab["platform_statement_no"]
    if ab["reviewer"]!="000045":raise ValueError("本笔尚未由直连再保账号领取，先完成待处理核对步骤")
    await authenticate("reinsurer","reinsurer","000045")
    await ctx.call("playwright.page_assert_text",{"selector":"body","text":"用户名称000045","role":"reinsurer"})
    await ctx.call("playwright.page_assert_url",{"url":processing_url,"role":"reinsurer"})
    await ctx.call("playwright.page_assert_value",{"selector":"#cedentTreatyNo","value":inputs["platform_treaty_no"],"role":"reinsurer"})
    await ctx.call("playwright.page_assert_value",{"selector":"input[id$='-10947283-platformStatementNo']","value":ab["platform_statement_no"],"role":"reinsurer"})
    decision={"kind":"label","value":"退回至分出人","exact":True}
    await ctx.call("playwright.page_assert_state",{"selector":decision,"expected":{"count":1,"visible":True,"enabled":True},"role":"reinsurer","timeout_ms":20000})
    await ctx.call("playwright.page_check",{"selector":decision,"checked":True,"role":"reinsurer"})
    await ctx.call("playwright.page_assert_checked",{"selector":decision,"checked":True,"role":"reinsurer"})
    watermark=await query("SELECT MAX(id) AS max_id FROM t_ri_gsc_onchain_record",[],"本笔首次直连退回record水位",1)
    if watermark["row_count"]!=1:raise ValueError("本笔record水位异常")
    reason=inputs["bill_label"]+" 直连再保退回分出人 V1 仅供本地自测"
    await ctx.call("playwright.page_fill",{"selector":"#comments","value":reason,"role":"reinsurer"})
    await ctx.call("playwright.page_assert_value",{"selector":"#comments","value":reason,"role":"reinsurer"})
    await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":"reinsurer"})
    await ctx.call("playwright.page_assert_url",{"url":"http://localhost:9877/ContractBill/list","role":"reinsurer","timeout_ms":20000})
    after=await query("SELECT statement_normal_id,org_code,reinsurance_role,statement_status FROM ri_statement_normal_state WHERE statement_normal_id=%s AND is_deleted='N' ORDER BY statement_normal_id,org_code",[inputs["normal_id"]],"首次退回后AB13/4及下游0/0",5)
    expected_after=[(inputs["normal_id"],"000045","02",4),(inputs["normal_id"],"000050","01",13)]
    if after["row_count"]!=2 or [(x["statement_normal_id"],x["org_code"],x["reinsurance_role"],int(x["statement_status"])) for x in after["rows"]]!=expected_after:raise ValueError("首次直连退回后角色状态不符，保留现场，不重复退回")
    backup=await query("SELECT id,source_table,source_id,is_deleted,SHA2(back_up_data,256) AS snapshot_sha256,back_up_data,JSON_UNQUOTE(JSON_EXTRACT(back_up_data,'$.comment')) AS frozen_comment FROM t_business_back_up_data WHERE source_table=3 AND source_id=%s ORDER BY id",[inputs["normal_id"]],"账单首次退回唯一V1快照",2)
    if backup["row_count"]!=1:raise ValueError("首次退回快照数目异常，不重复退回")
    snap=backup["rows"][0]
    if snap["is_deleted"]!="N" or snap["frozen_comment"]!=inputs["v1_comment"] or not snap["snapshot_sha256"]:raise ValueError("首次退回未冻结实际业务V1备注，不重复退回")
    return ctx.result(data={"statement_id":inputs["statement_id"],"record_no":inputs["record_no"],"bill_label":inputs["bill_label"],"platform_treaty_no":inputs["platform_treaty_no"],"normal_id":inputs["normal_id"],"source_table":3,"source_id":inputs["normal_id"],"snapshot_id":snap["id"],"snapshot_sha256":snap["snapshot_sha256"],"frozen_comment":snap["frozen_comment"],"v1_comment":inputs["v1_comment"],"ab_platform_no":ab["platform_statement_no"],"role_states":after["rows"],"reason":reason,"snapshot":snap,"initial_job":job,"after_record_id":watermark["rows"][0]["max_id"],"rejection_performed":True,"boundary":"本笔正常中文UI直连再保退回分出人；独立REJECT Mock；未验证真实record"})
