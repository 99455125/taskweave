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
    role_states=await query("SELECT statement_normal_id,org_code,reinsurance_role,statement_status FROM ri_statement_normal_state WHERE statement_normal_id IN (%s,%s) AND is_deleted='N' ORDER BY statement_normal_id,org_code",[inputs["normal_id"],inputs["downstream_normal_id"]],"本笔首次再保待确认阶段",5)
    expected=[(inputs["normal_id"],"000050","01",3),(inputs["normal_id"],"000053","02",5),(inputs["downstream_normal_id"],"000045","02",3),(inputs["downstream_normal_id"],"000053","01",3)]
    if role_states["row_count"]!=4 or [(x["statement_normal_id"],x["org_code"],x["reinsurance_role"],int(x["statement_status"])) for x in role_states["rows"]]!=expected:raise ValueError("本笔未处于首次再保待确认，不领取")
    item=await query("SELECT id,object_id,item_code,item_amount,item_comment,version FROM ri_statement_section_item WHERE object_type=0 AND object_id=%s AND version=2 AND is_deleted='N' ORDER BY id",[inputs["downstream_normal_id"]],"本笔再保收到的V1自有科目",2)
    if item["row_count"]!=1:raise ValueError("本笔再保收到的version2科目不唯一")
    custom=item["rows"][0]
    if custom["id"]!=inputs["custom_item_id"] or custom["item_code"]!="98" or str(custom["item_amount"])!="0.00" or custom["item_comment"]!=inputs["v1_item_comment"]:raise ValueError("本笔再保收到的自有V1科目不符")
    job=await query("SELECT b.id AS parent_id,b.group_id AS parent_group,b.status AS parent_status,d.id AS detail_id,d.group_id AS detail_group,d.status AS detail_status,d.biz_no,d.onchain_business_id,d.biz_id,d.callback_result,d.onchain_times FROM onchain_biz_job_info b JOIN onchain_job_detail_info d ON d.biz_job_id=b.id AND d.is_deleted='N' WHERE b.group_id=%s AND b.biz_no=%s AND b.job_task='TREATY_BILL_BROKER_PROCESS' AND b.is_deleted='N' ORDER BY b.id,d.id",[inputs["normal_id"],ab["platform_statement_no"]],"首次再保收到的唯一BC任务",2)
    if job["row_count"]!=1:raise ValueError("本笔首次BC任务不唯一")
    row=job["rows"][0]
    if row["parent_id"]!=inputs["initial_bc_parent_id"] or row["detail_id"]!=inputs["initial_bc_detail_id"] or row["parent_group"]!=inputs["normal_id"] or row["detail_group"]!=inputs["downstream_normal_id"] or row["onchain_business_id"]!=inputs["downstream_normal_id"] or row["biz_no"]!=bc["platform_statement_no"] or row["biz_id"]!=inputs["expected_bc_biz_id"] or row["parent_status"]!=8 or row["detail_status"]!=8 or row["callback_result"] not in ["成功","Success"] or row["onchain_times"]!=1:raise ValueError("首次BC任务身份或终态不符")
    snapshots=await query("SELECT id FROM t_business_back_up_data WHERE source_table=3 AND source_id IN (%s,%s) ORDER BY id",[inputs["normal_id"],inputs["downstream_normal_id"]],"首次再保退回前快照防重",2)
    if snapshots["row_count"]:raise ValueError("本笔已存在退回快照，不当作首次待确认")
    processing_url="http://localhost:9877/ContractBill/list/confirm?id="+str(inputs["statement_id"])+"&treatyCode="+inputs["platform_treaty_no"]+"&statementNormalId="+str(inputs["downstream_normal_id"])+"&status=3&treatyReinsurerId=10925282&recordNo="+bc["platform_statement_no"]
    if bc["reviewer"]!="000045":raise ValueError("本笔再保尚未领取，先完成待确认页核对")
    await ctx.call("playwright.page_assert_text",{"selector":"body","text":"用户名称000045","role":"reinsurer"})
    await ctx.call("playwright.page_assert_url",{"url":processing_url,"role":"reinsurer"})
    await ctx.call("playwright.page_assert_value",{"selector":"#cedentTreatyNo","value":inputs["platform_treaty_no"],"role":"reinsurer"})
    await ctx.call("playwright.page_assert_value",{"selector":"input[id$='-10925282-platformStatementNo']","value":bc["platform_statement_no"],"role":"reinsurer"})
    await ctx.call("playwright.page_assert_state",{"selector":"input[id$='_itemComment']","expected":{"count":1,"editable":False},"role":"reinsurer"})
    await ctx.call("playwright.page_assert_value",{"selector":"input[id$='_itemComment']","value":inputs["v1_item_comment"],"role":"reinsurer"})
    watermark=await query("SELECT MAX(id) AS max_id FROM t_ri_gsc_onchain_record",[],"本笔首次再保退回前record水位",1)
    if watermark["row_count"]!=1:raise ValueError("本笔退回前record水位异常")
    decision={"kind":"label","value":"退回至经纪人","exact":True}
    await ctx.call("playwright.page_assert_state",{"selector":decision,"expected":{"count":1,"visible":True,"enabled":True},"role":"reinsurer","timeout_ms":20000})
    await ctx.call("playwright.page_check",{"selector":decision,"checked":True,"role":"reinsurer"})
    await ctx.call("playwright.page_assert_checked",{"selector":decision,"checked":True,"role":"reinsurer"})
    reason=inputs["bill_label"]+" 再保人退回经纪人 V1 仅供本地自测"
    await ctx.call("playwright.page_fill",{"selector":"#comments","value":reason,"role":"reinsurer"})
    await ctx.call("playwright.page_assert_value",{"selector":"#comments","value":reason,"role":"reinsurer"})
    await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":"reinsurer"})
    await ctx.call("playwright.page_assert_url",{"url":"http://localhost:9877/ContractBill/list","role":"reinsurer","timeout_ms":20000})
    after=await query("SELECT statement_normal_id,org_code,reinsurance_role,statement_status FROM ri_statement_normal_state WHERE statement_normal_id IN (%s,%s) AND is_deleted='N' ORDER BY statement_normal_id,org_code",[inputs["normal_id"],inputs["downstream_normal_id"]],"首次再保退回后AB3/13及BC4/4",5)
    expected_after=[(inputs["normal_id"],"000050","01",3),(inputs["normal_id"],"000053","02",13),(inputs["downstream_normal_id"],"000045","02",4),(inputs["downstream_normal_id"],"000053","01",4)]
    if after["row_count"]!=4 or [(x["statement_normal_id"],x["org_code"],x["reinsurance_role"],int(x["statement_status"])) for x in after["rows"]]!=expected_after:raise ValueError("首次再保退回后角色状态不符，不重复退回")
    backup=await query("SELECT id,source_table,source_id,is_deleted,SHA2(back_up_data,256) AS snapshot_sha256,back_up_data,JSON_CONTAINS(JSON_EXTRACT(back_up_data,'$.generalGroup[*].statementNormals[*].items[*]'),JSON_OBJECT('itemCode','98','itemAmount',0,'itemComment',%s,'version',2)) AS has_v1_item FROM t_business_back_up_data WHERE source_table=3 AND source_id IN (%s,%s) ORDER BY id",[inputs["v1_item_comment"],inputs["normal_id"],inputs["downstream_normal_id"]],"本笔首次BC快照全文及V1零科目冻结",2)
    if backup["row_count"]!=1:raise ValueError("首次再保退回应只产生BC一条快照，不重复退回")
    frozen=backup["rows"][0]
    if frozen["source_id"]!=inputs["downstream_normal_id"] or frozen["source_table"]!=3 or frozen["is_deleted"]!="N" or not frozen["snapshot_sha256"] or frozen["has_v1_item"]!=1:raise ValueError("首次再保退回BC来源或实际V1零科目冻结不符，不重复退回")
    live=await query("SELECT id,object_id,item_code,item_amount,item_comment,version FROM ri_statement_section_item WHERE object_type=0 AND object_id=%s AND version=2 AND is_deleted='N' ORDER BY id",[inputs["downstream_normal_id"]],"首次退回不改变实时自有V1科目",2)
    if live["row_count"]!=1 or live["rows"][0]!=custom:raise ValueError("首次退回意外改变实时自有科目")
    return ctx.result(data={"statement_id":inputs["statement_id"],"record_no":inputs["record_no"],"bill_label":inputs["bill_label"],"platform_treaty_no":inputs["platform_treaty_no"],"normal_id":inputs["normal_id"],"downstream_normal_id":inputs["downstream_normal_id"],"source_table":3,"source_id":inputs["downstream_normal_id"],"ab_platform_no":ab["platform_statement_no"],"bc_platform_no":bc["platform_statement_no"],"expected_biz_id":inputs["expected_biz_id"],"expected_bc_biz_id":inputs["expected_bc_biz_id"],"v1_comment":inputs["v1_comment"],"custom_item":custom,"v1_item_comment":inputs["v1_item_comment"],"initial_bc_job":row,"role_states":after["rows"],"snapshot_id":frozen["id"],"snapshot_sha256":frozen["snapshot_sha256"],"snapshot":frozen,"reason":reason,"after_record_id":watermark["rows"][0]["max_id"],"first_rejection_performed":True,"boundary":"正常中文UI045首次退053，AB3/13 BC4/4；source3 BC独立快照全文及98零额version2 V1确实冻结；Mock不证明真实record"})
