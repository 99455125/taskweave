async def run(ctx, inputs):
    async def authenticate(role,account_key,expected_account):
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
        await ctx.call("playwright.page_open", {"url": ui["url"], "role": role})
        await ctx.call("playwright.page_assert_state", {
            "selector": "#username", "expected": {"count": 1, "visible": True}, "role": role
        })
        # Explicitly choose Chinese; browser locale alone does not change product language.
        await ctx.call("playwright.page_click", {
            "selector": "#root > div:nth-of-type(1) > div:nth-of-type(3) > div:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(1) > form:nth-of-type(1) > div:nth-of-type(4) > div:nth-of-type(1) > div:nth-of-type(1)", "role": role
        })
        await ctx.call("playwright.page_click", {
            "selector": {"kind": "role", "value": "option", "name": "中文", "exact": True}, "role": role
        })
        placeholder = await ctx.call("playwright.page_attribute", {
            "selector": "#username", "name": "placeholder", "role": role
        })
        if placeholder["value"] != "请输入用户名":
            raise ValueError("登录页未完成中文切换")
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
    views=[]
    for target in inputs["role_views"]:
        role=target["role"]
        await authenticate(role,target["account_key"],target["account"])
        url="http://localhost:9877/ContractBill/list/view?id="+str(inputs["statement_id"])+"&treatyCode="+inputs["platform_treaty_no"]+"&statementNormalId="+str(target["normal_id"])+"&status=8&treatyReinsurerId="+str(target["party_id"])+"&recordNo="+target["platform_statement_no"]
        await ctx.call("playwright.page_open",{"url":url,"role":role})
        await ctx.call("playwright.page_assert_value",{"selector":"#cedentTreatyNo","value":inputs["platform_treaty_no"],"role":role})
        await ctx.call("playwright.page_assert_value",{"selector":"#accountPeriod","value":inputs["account_period"],"role":role})
        await ctx.call("playwright.page_assert_value",{"selector":"#statementDate","value":inputs["statement_start_date"],"role":role})
        views.append({"role":role,"account":target["account"],"normal_id":target["normal_id"],"url":url})
    master=await ctx.call("tidb.query",{"sql":"SELECT id,treaty_id,record_no,statement_status,statement_start_date,statement_end_date,account_period,comment FROM ri_statement WHERE id=%s AND input_org_code='000050' AND is_deleted='N'","params":[inputs["statement_id"]],"max_rows":2,"title":"最终账单主表聚合状态"})
    if master["truncated"] or master["row_count"]!=1:raise ValueError("账单主表不唯一")
    parent=master["rows"][0]
    if parent["treaty_id"]!=inputs["treaty_master_id"] or parent["record_no"]!=inputs["record_no"] or parent["account_period"]!=inputs["account_period"] or parent["comment"]!="仅供本地自测 "+inputs["bill_label"]:raise ValueError("账单主表关键字段变化")
    rows=await ctx.call("tidb.query",{"sql":"SELECT n.id,n.input_org_code,n.enter_org_code,n.parent_id,n.net_balance,n.biz_id,n.platform_statement_no,s.org_code,s.statement_status FROM ri_statement_normal n JOIN ri_statement_normal_state s ON s.statement_normal_id=n.id AND s.is_deleted='N' WHERE n.statement_id=%s AND n.is_deleted='N' ORDER BY n.id,s.org_code","params":[inputs["statement_id"]],"max_rows":10,"title":"最终账单四角色状态"})
    expected=[(inputs["normal_ids"][0],"000050"),(inputs["normal_ids"][0],"000053"),(inputs["normal_ids"][1],"000045"),(inputs["normal_ids"][1],"000053")]
    if rows["truncated"] or [(r["id"],r["org_code"]) for r in rows["rows"]]!=expected or any(r["statement_status"]!=8 or str(r["net_balance"])!=inputs["expected_balance"] for r in rows["rows"]):raise ValueError("账单角色未全部完成或金额变化")
    saved=rows["rows"]
    if any(r["parent_id"] is not None or (r["input_org_code"],r["enter_org_code"])!=("000050","000053") or r["biz_id"]!=inputs["mock_biz_ids"][0] for r in saved[:2]):raise ValueError("账单上游父子关系或Mock bizId不符")
    if any(r["parent_id"]!=inputs["normal_ids"][0] or (r["input_org_code"],r["enter_org_code"])!=("000053","000045") or r["biz_id"]!=inputs["mock_biz_ids"][1] for r in saved[2:]):raise ValueError("账单下游父子关系或Mock bizId不符")
    items=await ctx.call("tidb.query",{"sql":"SELECT object_id,item_code,item_amount FROM ri_statement_section_item WHERE object_type=0 AND object_id IN (%s,%s) AND is_deleted='N' ORDER BY object_id,item_code","params":inputs["normal_ids"],"max_rows":20,"title":"最终账单科目"})
    expected_items=[(normal,i["code"],i["amount"]) for normal in inputs["normal_ids"] for i in inputs["expected_items"]]
    if items["truncated"] or [(r["object_id"],r["item_code"],str(r["item_amount"])) for r in items["rows"]]!=expected_items:raise ValueError("最终账单科目变化")
    jobs=await ctx.call("tidb.query",{"sql":"SELECT d.id,d.biz_job_id,b.status AS parent_status,b.group_id,b.job_task,b.operation_type,d.onchain_business_id,d.biz_no,d.status,d.`from`,d.`to`,d.biz_id,d.callback_result FROM onchain_job_detail_info d JOIN onchain_biz_job_info b ON b.id=d.biz_job_id AND b.is_deleted='N' WHERE d.onchain_business_id IN (%s,%s) AND b.job_task IN ('TREATY_BILL_PROCESS','TREATY_BILL_BROKER_PROCESS') AND d.is_deleted='N' ORDER BY d.id","params":inputs["normal_ids"],"max_rows":10,"title":"最终账单核心Mock任务与回调"})
    if jobs["truncated"] or jobs["row_count"]!=2 or [(r["from"],r["to"],r["job_task"]) for r in jobs["rows"]]!=[("000050","000053","TREATY_BILL_PROCESS"),("000053","000045","TREATY_BILL_BROKER_PROCESS")]:raise ValueError("账单核心Mock任务范围不符")
    if any(r["status"]!=8 or r["parent_status"]!=8 or r["callback_result"]!="成功" for r in jobs["rows"]):raise ValueError("账单核心Mock回调未完成")
    if [r["biz_id"] for r in jobs["rows"]]!=inputs["mock_biz_ids"] or [r["onchain_business_id"] for r in jobs["rows"]]!=inputs["normal_ids"]:raise ValueError("核心任务映射与本轮账单不符")
    records=await ctx.call("tidb.query",{"sql":"SELECT id,biz_id,msg_name,otc_flag FROM t_ri_gsc_onchain_record WHERE biz_id IN (%s,%s) ORDER BY id","params":inputs["mock_biz_ids"],"max_rows":20,"title":"Mock与真实record边界"})
    if records["truncated"]:raise ValueError("record查询截断")
    if parent["statement_status"]!=inputs["expected_master_status"]:raise ValueError("四角色已完成，但主表聚合状态仍为"+str(parent["statement_status"])+"，不能判定整笔账单完成；保留三方详情，等待根因确认")
    return ctx.result(data={"master":parent,"role_states":saved,"items":items["rows"],"core_mock_jobs":jobs["rows"],"role_views":views,"record_count":records["row_count"],"record_source_verified":False,"list_verified":False,"local_mock_business_completed":True,"boundary":"仅本地Mock业务和三方详情；真实record来源、真实链节点与列表完整性由后续独立步骤验收。"})
