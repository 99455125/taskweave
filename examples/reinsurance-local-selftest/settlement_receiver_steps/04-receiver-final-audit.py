async def run(ctx, inputs):
    async def authenticate():
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
    role=inputs["role"]
    verify_only=inputs.get("verify_finalized_only",False)
    guard=await ctx.call("tidb.query",{"sql":"SELECT s.id,s.institution_settlement_no,s.comments,s.currency,s.total_amount,r.id AS task_id,r.org_code,r.status,r.review_level,r.reviewer FROM ri_settlement s JOIN ri_settlement_reinsurer r ON r.settlement_no=s.settlement_no AND r.is_deleted='N' WHERE s.id=%s AND s.settlement_no=%s AND s.from_org_code='000050' AND s.to_org_code='000053' AND s.is_deleted='N' ORDER BY r.business_type","params":[inputs["settlement_id"],inputs["settlement_no"]],"max_rows":3,"title":"接收方一级审核双任务守卫"})
    if guard["truncated"] or guard["row_count"]!=2 or [(r["task_id"],r["org_code"],str(r["status"])) for r in guard["rows"]]!=[(inputs["from_task_id"],"000050","6" if verify_only else "3"),(inputs["to_task_id"],"000053","6" if verify_only else "1")]:raise ValueError("审核前双方任务状态不符")
    if any(r["institution_settlement_no"]!=inputs["run_label"] or r["comments"]!="仅供本地自测 "+inputs["run_label"] or r["currency"]!="SETTLE-CNY" or str(r["total_amount"])!=inputs["expected_amount"] for r in guard["rows"]):raise ValueError("审核前归属或金额变化")
    finance=await ctx.call("file.read",{"path":inputs["finance_handoff_path"],"format":"json","max_bytes":65536})
    evidence=finance["content"]
    if not evidence.get("loopbackOnly") or not evidence.get("confirmationEnabled") or not evidence.get("finalHealth",{}).get("allFinancePathsLoopback") or not evidence.get("syntheticBalanceVerification"):raise ValueError("本地资金隔离及余额前置交接不完整，停止最终确认")
    if not verify_only:
        sender=guard["rows"][1]
        if str(sender["review_level"])!="2" or sender["reviewer"] not in [None,"","000053"]:raise ValueError("审核级次或领取人变化，不重复最终审核")
        await authenticate()
        await ctx.call("playwright.page_open",{"url":"http://localhost:9877/SettlementManagement/BillSettlement","role":role})
        await ctx.call("playwright.page_assert_text",{"selector":"body","text":"用户名称000053","role":role})
        card='div[class*="list-item_"]:has(span:text-is("'+inputs["settlement_no"]+'"))'
        await ctx.call("playwright.page_assert_state",{"selector":card,"expected":{"count":1,"visible":True},"role":role})
        await ctx.call("playwright.page_assert_text",{"selector":card,"text":"70,000.00","role":role})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"处 理","exact":True,"within":{"kind":"css","value":card}},"role":role})
        await ctx.call("playwright.page_assert_value",{"selector":"#settlementNo","value":inputs["settlement_no"],"role":role})
        await ctx.call("playwright.page_assert_value",{"selector":"#institutionSettlementNo","value":inputs["run_label"],"role":role})
        decision={"kind":"label","value":"本公司同意并确认","exact":True}
        await ctx.call("playwright.page_assert_state",{"selector":decision,"expected":{"count":1,"visible":True},"role":role})
        await ctx.call("playwright.page_check",{"selector":decision,"checked":True,"role":role})
        await ctx.call("playwright.page_fill",{"selector":"#auditComments","value":"仅供本地自测 接收方最终审核 "+inputs["run_label"],"role":role})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":role})
        await ctx.call("playwright.page_assert_url",{"url":"http://localhost:9877/SettlementManagement/BillSettlement","role":role})
    waiting=await ctx.call("process.run",{"executable":"/Users/xiaojuju/Projects/company/bjs/dev-environment/imports/verify-venv/bin/python","args":["/Users/xiaojuju/Projects/company/bjs/dev-environment/test-support/wait_owned_settlement_callback.py","--phase","confirm"],"timeout_seconds":45,"max_output_bytes":65536})
    ctx.log("限定本轮只读回调等待="+waiting["stdout"])
    if waiting["exit_code"]!=0 or waiting["stdout_truncated"] or waiting["stderr_truncated"]:raise ValueError("回调仍在处理或等待检查异常；保留最后状态，不重提或重放")
    after=await ctx.call("tidb.query",{"sql":"SELECT id,org_code,status,review_level,reviewer,from_id FROM ri_settlement_reinsurer WHERE settlement_no=%s AND is_deleted='N' ORDER BY business_type","params":[inputs["settlement_no"]],"max_rows":3,"title":"接收方最终审核后待结算"})
    if after["truncated"] or [(r["id"],r["org_code"]) for r in after["rows"]]!=[(inputs["from_task_id"],"000050"),(inputs["to_task_id"],"000053")]:raise ValueError("最终审核后任务归属变化")
    jobs=await ctx.call("tidb.query",{"sql":"SELECT b.id AS parent_id,b.status AS parent_status,b.group_id,b.job_task,d.id AS detail_id,d.status,d.biz_no,d.onchain_business_id,d.biz_id,d.tx_id,d.callback_result FROM onchain_biz_job_info b JOIN onchain_job_detail_info d ON d.biz_job_id=b.id AND d.is_deleted='N' WHERE b.group_id=%s AND b.job_task='SETTLEMENT_CONFIRM_PROCESS' AND b.is_deleted='N' ORDER BY d.id","params":[inputs["to_task_id"]],"max_rows":3,"title":"限定本轮结算确认核心Mock任务"})
    if jobs["truncated"] or jobs["row_count"]>1:raise ValueError("结算确认核心任务范围不唯一")
    ctx.log("最终审核状态与Mock任务="+str({"roles":after["rows"],"jobs":jobs["rows"]}))
    if not all(str(r["status"])=="6" for r in after["rows"]) or jobs["row_count"]!=1:raise ValueError("尚未待结算或确认任务未唯一生成，不重复审核")
    job=jobs["rows"][0]
    if job["status"]!=8 or job["parent_status"]!=8 or job["callback_result"]!='{"code":"0"}' or job["biz_no"]!=inputs["settlement_no"] or job["onchain_business_id"]!=inputs["from_task_id"] or job["biz_id"]!="owned-local-settlement-tw-174791" or not job["tx_id"]:raise ValueError("确认Mock任务、回调、tx或映射异常，只读诊断不重提")
    master=await ctx.call("tidb.query",{"sql":"SELECT id,settlement_no,institution_settlement_no,currency,total_amount,payer_org_code,receiver_org_code,biz_id,tx_id,busi_order_no FROM ri_settlement WHERE id=%s AND is_deleted='N'","params":[inputs["settlement_id"]],"max_rows":2,"title":"本轮待结算与本地数据接收流水"})
    if master["truncated"] or master["row_count"]!=1:raise ValueError("结算主表不唯一")
    m=master["rows"][0]
    if m["settlement_no"]!=inputs["settlement_no"] or m["institution_settlement_no"]!=inputs["run_label"] or m["currency"]!="SETTLE-CNY" or str(m["total_amount"])!=inputs["expected_amount"] or (m["payer_org_code"],m["receiver_org_code"])!=("000050","000053") or m["biz_id"]!="owned-local-settlement-tw-174791" or not m["busi_order_no"]:raise ValueError("待结算主表、金额或本地接收流水不符")
    receipt=await ctx.call("tidb.query",{"sql":"SELECT id,interface_code,business_id,business_no,business_transaction_no,response_code,response_message,JSON_UNQUOTE(JSON_EXTRACT(request_json,'$.payOrderNo')) AS pay_order_no FROM ri_integration_log WHERE business_id=%s AND business_no=%s AND interface_code='FINANCE_API_DATA_UPLOAD_URL' AND is_deleted='N' ORDER BY id","params":[inputs["settlement_id"],inputs["settlement_no"]],"max_rows":3,"title":"本笔本地清分数据接收响应；不读取账户和密钥"})
    if receipt["truncated"] or receipt["row_count"]!=1:raise ValueError("清分数据接收记录不唯一")
    r=receipt["rows"][0]
    if r["response_code"]!="0001" or "LOCAL MOCK" not in r["response_message"] or r["pay_order_no"]!=inputs["settlement_no"] or r["business_transaction_no"]!=m["busi_order_no"]:raise ValueError("本地接收响应或本轮流水映射不符")
    statement=await ctx.call("tidb.query",{"sql":"SELECT id,settlement_id,settlement_status,currency,net_balance FROM ri_statement_normal WHERE id=%s AND statement_id=544940 AND is_deleted='N'","params":[inputs["normal_id"]],"max_rows":2,"title":"关联账单待结算状态"})
    if statement["truncated"] or statement["row_count"]!=1 or statement["rows"][0]["settlement_id"]!=inputs["settlement_id"] or str(statement["rows"][0]["settlement_status"])!="6" or statement["rows"][0]["currency"]!="CNY" or str(statement["rows"][0]["net_balance"])!=inputs["expected_amount"]:raise ValueError("关联账单结算状态或金额不符")
    return ctx.result(data={"settlement_id":inputs["settlement_id"],"settlement_no":inputs["settlement_no"],"from_task_id":inputs["from_task_id"],"to_task_id":inputs["to_task_id"],"normal_id":inputs["normal_id"],"run_label":inputs["run_label"],"role_states":after["rows"],"master":m,"core_mock_job":job,"local_receipt":r,"statement":statement["rows"][0],"receiver_audit_completed":True,"verified_finalized_only":verify_only,"payment_completed":False,"record_source_verified":False,"boundary":"仅本地待结算6和模拟清分数据接收；合成余额及双签不代表真实资金/签名，原发起tx缺失证据保留；确认tx亦为Mock，真实record另验收"})
