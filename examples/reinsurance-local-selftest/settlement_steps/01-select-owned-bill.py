async def run(ctx, inputs):
    # Existing local credentials stay outside portable task packages and outputs.
    credentials = await ctx.call("file.read", {
        "path": inputs["credentials_path"], "format": "json", "max_bytes": 65536
    })
    ui = credentials["content"]["ui"]
    if ui["url"] != "http://localhost:9877/login":
        raise ValueError("凭据仅允许用于交接指定的本地登录地址")
    role = inputs["role"]
    account = ui["accounts"][inputs["account_key"]]
    if account != inputs["expected_account"] or not ui["sharedPassword"]:
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
    existing=await ctx.call("tidb.query",{"sql":"SELECT s.id,s.settlement_no,s.currency,s.settlement_type,s.institution_settlement_no,s.comments,s.from_org_code,s.to_org_code,r.id AS task_id,r.status FROM ri_settlement s JOIN ri_settlement_reinsurer r ON r.settlement_no=s.settlement_no AND r.business_type='1' AND r.org_code='000050' AND r.is_deleted='N' WHERE s.id=%s AND s.is_deleted='N'","params":[inputs["settlement_id"]],"max_rows":2,"title":"本轮已创建结算草稿归属守卫"})
    if existing["truncated"] or existing["row_count"]!=1:raise ValueError("本轮结算草稿不唯一")
    s=existing["rows"][0]
    if s["settlement_no"]!=inputs["settlement_no"] or s["task_id"]!=inputs["from_task_id"] or (s["from_org_code"],s["to_org_code"],s["currency"],str(s["settlement_type"]),str(s["status"]))!=("000050","000053","SETTLE-CNY","1","0") or s["institution_settlement_no"] not in [None,"",inputs["run_label"]] or s["comments"] not in [None,"","仅供本地自测 "+inputs["run_label"]]:raise ValueError("草稿归属、币种或状态变化，停止")
    n=await ctx.call("tidb.query",{"sql":"SELECT n.id,n.net_balance,n.currency,n.settlement_id,n.sign_biz_id,n.sign_file_id,n.platform_statement_no,s.statement_status FROM ri_statement_normal n JOIN ri_statement_normal_state s ON s.statement_normal_id=n.id AND s.org_code='000050' AND s.is_deleted='N' WHERE n.id=%s AND n.statement_id=544940 AND n.input_org_code='000050' AND n.enter_org_code='000053' AND n.is_deleted='N'","params":[inputs["normal_id"]],"max_rows":2,"title":"本轮账单可结算前置"})
    if n["truncated"] or n["row_count"]!=1:raise ValueError("本轮账单不唯一")
    row=n["rows"][0]
    if row["statement_status"]!=8 or str(row["net_balance"])!="70000.00" or row["currency"]!="CNY" or row["settlement_id"] is not None or not row["sign_biz_id"] or not row["sign_file_id"] or row["platform_statement_no"]!=inputs["platform_statement_no"]:raise ValueError("本轮账单不可选或已被占用")
    detail=await ctx.call("tidb.query",{"sql":"SELECT id FROM ri_settlement_statement WHERE settlement_no=%s AND is_deleted='N'","params":[inputs["settlement_no"]],"max_rows":2,"title":"禁止重复添加结算明细"})
    if detail["truncated"] or detail["row_count"]:raise ValueError("本轮草稿已有明细，停止重复添加；按保存后步骤续接")
    await ctx.call("playwright.page_open",{"url":"http://localhost:9877/SettlementManagement/BillSettlement/edit?taskId="+str(inputs["from_task_id"]),"role":role})
    await ctx.call("playwright.page_assert_value",{"selector":"#settlementNo","value":inputs["settlement_no"],"role":role})
    await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"link","name":"结算单明细信息","exact":True},"role":role})
    await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"添加账单","exact":True},"role":role})
    await ctx.call("playwright.page_fill",{"selector":"#platformStatementNo","value":inputs["platform_statement_no"],"role":role})
    await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"查 询","exact":True},"role":role})
    target='tr:has(a:text-is("'+inputs["platform_statement_no"]+'"))'
    await ctx.call("playwright.page_assert_state",{"selector":target,"expected":{"count":1,"visible":True},"role":role})
    await ctx.call("playwright.page_check",{"selector":target+' input[type="checkbox"]',"checked":True,"role":role})
    await ctx.call("playwright.page_assert_checked",{"selector":target+' input[type="checkbox"]',"checked":True,"role":role})
    return ctx.result(data={"settlement_id":s["id"],"settlement_no":s["settlement_no"],"from_task_id":s["task_id"],"to_task_id":inputs["to_task_id"],"normal_id":row["id"],"platform_statement_no":row["platform_statement_no"],"settlement_currency":s["currency"],"statement_currency":row["currency"],"expected_amount":"70000.00","run_label":inputs["run_label"],"selected":True,"selection_persisted":False,"creation_evidence_run":"ad3e31fa-604c-42ad-b84b-1951bd8439ee","boundary":"仅本轮已创建草稿续接；双签为精确本地Mock；尚未点击添加账单确定和保存"})
