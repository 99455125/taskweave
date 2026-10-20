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
    verify_only=inputs.get("verify_submitted_only",False)
    guard=await ctx.call("tidb.query",{"sql":"SELECT s.id,s.institution_settlement_no,s.comments,s.currency,s.total_amount,r.id AS task_id,r.org_code,r.status,r.business_type FROM ri_settlement s JOIN ri_settlement_reinsurer r ON r.settlement_no=s.settlement_no AND r.is_deleted='N' WHERE s.id=%s AND s.settlement_no=%s AND s.from_org_code='000050' AND s.to_org_code='000053' AND s.is_deleted='N' ORDER BY r.business_type","params":[inputs["settlement_id"],inputs["settlement_no"]],"max_rows":3,"title":"保存默认汇率前双任务守卫"})
    if guard["truncated"] or guard["row_count"]!=2 or [(r["task_id"],r["org_code"],str(r["status"])) for r in guard["rows"]]!=[(inputs["from_task_id"],"000050","1" if verify_only else "0"),(inputs["to_task_id"],"000053","0")]:raise ValueError("本轮结算任务状态变化，停止保存")
    if any(r["institution_settlement_no"]!=inputs["run_label"] or r["comments"]!="仅供本地自测 "+inputs["run_label"] or r["currency"]!="SETTLE-CNY" or str(r["total_amount"])!=inputs["expected_amount"] for r in guard["rows"]):raise ValueError("结算归属或金额变化")
    details=await ctx.call("tidb.query",{"sql":"SELECT id,statement_normal_id,statement_amount,settlement_amount,settlement_currency_exchange_rate,statement_currency_exchange_rate FROM ri_settlement_statement WHERE settlement_no=%s AND is_deleted='N'","params":[inputs["settlement_no"]],"max_rows":2,"title":"提交前结算金额与汇率已落库"})
    if details["truncated"] or details["row_count"]!=1:raise ValueError("提交前明细不唯一")
    d=details["rows"][0]
    if str(d["statement_normal_id"])!=str(inputs["normal_id"]) or any(str(d[k])!=inputs["expected_amount"] for k in ["statement_amount","settlement_amount"]) or any(float(d[k])!=100 for k in ["settlement_currency_exchange_rate","statement_currency_exchange_rate"]):raise ValueError("提交前明细金额或汇率变化")
    after_record_id=inputs["recovery_after_record_id"] if verify_only else None
    if not verify_only:
        jobs=await ctx.call("tidb.query",{"sql":"SELECT id,status FROM onchain_biz_job_info WHERE group_id=%s AND job_task='SETTLEMENT_PROCESS' AND is_deleted='N'","params":[inputs["from_task_id"]],"max_rows":2,"title":"提交前禁止重复结算上链任务"})
        if jobs["truncated"] or jobs["row_count"]:raise ValueError("本轮已有结算发起任务，停止重提，按原任务状态诊断")
        record_before=await ctx.call("tidb.query",{"sql":"SELECT COALESCE(MAX(id),0) AS after_record_id FROM t_ri_gsc_onchain_record","max_rows":1,"title":"本轮结算提交前record水位"})
        after_record_id=record_before["rows"][0]["after_record_id"]
        ctx.log("本轮结算提交前record水位="+str(after_record_id))
        await authenticate()
        await ctx.call("playwright.page_open",{"url":"http://localhost:9877/SettlementManagement/BillSettlement","role":role})
        await ctx.call("playwright.page_open",{"url":"http://localhost:9877/SettlementManagement/BillSettlement/edit?taskId="+str(inputs["from_task_id"]),"role":role})
        await ctx.call("playwright.page_assert_value",{"selector":"#settlementNo","value":inputs["settlement_no"],"role":role})
        await ctx.call("playwright.page_assert_value",{"selector":"#institutionSettlementNo","value":inputs["run_label"],"role":role})
        decision={"kind":"label","value":"确认并提交审核","exact":True}
        await ctx.call("playwright.page_assert_state",{"selector":decision,"expected":{"count":1,"visible":True},"role":role})
        await ctx.call("playwright.page_check",{"selector":decision,"checked":True,"role":role})
        await ctx.call("playwright.page_fill",{"selector":"#auditComments","value":"仅供本地自测 提交 "+inputs["run_label"],"role":role})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":role})
        await ctx.call("playwright.page_assert_url",{"url":"http://localhost:9877/SettlementManagement/BillSettlement","role":role})
    after=await ctx.call("tidb.query",{"sql":"SELECT id,org_code,business_type,status,review_level,reviewer,biz_id FROM ri_settlement_reinsurer WHERE settlement_no=%s AND is_deleted='N' ORDER BY business_type","params":[inputs["settlement_no"]],"max_rows":3,"title":"结算提交后真实状态与审核级次"})
    if after["truncated"] or after["row_count"]!=2 or [(r["id"],r["org_code"],str(r["status"])) for r in after["rows"]]!=[(inputs["from_task_id"],"000050","1"),(inputs["to_task_id"],"000053","0")]:raise ValueError("提交后的审核任务状态不符；保留结果，不重提")
    binding=await ctx.call("tidb.query",{"sql":"SELECT id,settlement_id,currency,net_balance FROM ri_statement_normal WHERE id=%s AND statement_id=544940 AND is_deleted='N'","params":[inputs["normal_id"]],"max_rows":2,"title":"提交后本轮账单绑定"})
    if binding["truncated"] or binding["row_count"]!=1 or binding["rows"][0]["settlement_id"]!=inputs["settlement_id"] or binding["rows"][0]["currency"]!="CNY" or str(binding["rows"][0]["net_balance"])!=inputs["expected_amount"]:raise ValueError("提交后账单归属、绑定或金额异常")
    if str(after["rows"][0]["review_level"])!="1":raise ValueError("提交恢复已超过一级审核前置，保留实际进度，不重提")
    return ctx.result(data={"settlement_id":inputs["settlement_id"],"settlement_no":inputs["settlement_no"],"from_task_id":inputs["from_task_id"],"to_task_id":inputs["to_task_id"],"normal_id":inputs["normal_id"],"run_label":inputs["run_label"],"after_record_id":after_record_id,"role_states":after["rows"],"submitted_to_review":True,"verified_submitted_only":verify_only,"statement_binding":binding["rows"][0],"sender_audit_completed":False,"boundary":"只完成提交至发起方审核；合成余额仅本地Mock，机构审核另一步"})
