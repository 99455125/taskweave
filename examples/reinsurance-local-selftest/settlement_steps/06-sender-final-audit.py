async def run(ctx, inputs):
    role=inputs["role"]
    verify_only=inputs.get("verify_audited_only",False)
    guard=await ctx.call("tidb.query",{"sql":"SELECT s.id,s.institution_settlement_no,s.comments,s.currency,s.total_amount,r.id AS task_id,r.org_code,r.status,r.review_level,r.reviewer FROM ri_settlement s JOIN ri_settlement_reinsurer r ON r.settlement_no=s.settlement_no AND r.is_deleted='N' WHERE s.id=%s AND s.settlement_no=%s AND s.from_org_code='000050' AND s.to_org_code='000053' AND s.is_deleted='N' ORDER BY r.business_type","params":[inputs["settlement_id"],inputs["settlement_no"]],"max_rows":3,"title":"发起方一级审核双任务守卫"})
    if guard["truncated"] or guard["row_count"]!=2 or [(r["task_id"],r["org_code"],str(r["status"])) for r in guard["rows"]]!=[(inputs["from_task_id"],"000050","3" if verify_only else "1"),(inputs["to_task_id"],"000053","3" if verify_only else "0")]:raise ValueError("审核前双方任务状态不符")
    if any(r["institution_settlement_no"]!=inputs["run_label"] or r["comments"]!="仅供本地自测 "+inputs["run_label"] or r["currency"]!="SETTLE-CNY" or str(r["total_amount"])!=inputs["expected_amount"] for r in guard["rows"]):raise ValueError("审核前归属或金额变化")
    if not verify_only:
        sender=guard["rows"][0]
        if str(sender["review_level"])!="2" or sender["reviewer"] not in [None,"","000050"]:raise ValueError("审核级次或领取人变化，不重复二级审核")
        await ctx.call("playwright.page_open",{"url":"http://localhost:9877/SettlementManagement/BillSettlement","role":role})
        await ctx.call("playwright.page_assert_text",{"selector":"body","text":"用户名称000050","role":role})
        card='div[class*="list-item_"]:has(span:text-is("'+inputs["settlement_no"]+'"))'
        await ctx.call("playwright.page_assert_state",{"selector":card,"expected":{"count":1,"visible":True},"role":role})
        await ctx.call("playwright.page_assert_text",{"selector":card,"text":"70,000.00","role":role})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"处 理","exact":True,"within":{"kind":"css","value":card}},"role":role})
        await ctx.call("playwright.page_assert_value",{"selector":"#settlementNo","value":inputs["settlement_no"],"role":role})
        await ctx.call("playwright.page_assert_value",{"selector":"#institutionSettlementNo","value":inputs["run_label"],"role":role})
        decision={"kind":"label","value":"本公司确认并提交至对手方","exact":True}
        await ctx.call("playwright.page_assert_state",{"selector":decision,"expected":{"count":1,"visible":True},"role":role})
        await ctx.call("playwright.page_check",{"selector":decision,"checked":True,"role":role})
        await ctx.call("playwright.page_fill",{"selector":"#auditComments","value":"仅供本地自测 发起方二级审核 "+inputs["run_label"],"role":role})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":role})
        await ctx.call("playwright.page_assert_url",{"url":"http://localhost:9877/SettlementManagement/BillSettlement","role":role})
    waiting=await ctx.call("process.run",{"executable":"/Users/xiaojuju/Projects/company/bjs/dev-environment/imports/verify-venv/bin/python","args":["/Users/xiaojuju/Projects/company/bjs/dev-environment/test-support/wait_owned_settlement_callback.py","--phase","submit"],"timeout_seconds":45,"max_output_bytes":65536})
    ctx.log("限定本轮只读回调等待="+waiting["stdout"])
    if waiting["exit_code"]!=0 or waiting["stdout_truncated"] or waiting["stderr_truncated"]:raise ValueError("回调仍在处理或等待检查异常；保留最后状态，不重提或重放")
    after=await ctx.call("tidb.query",{"sql":"SELECT id,org_code,status,review_level,reviewer,biz_id FROM ri_settlement_reinsurer WHERE settlement_no=%s AND is_deleted='N' ORDER BY business_type","params":[inputs["settlement_no"]],"max_rows":3,"title":"发起方最终审核后双方待确认"})
    jobs=await ctx.call("tidb.query",{"sql":"SELECT b.id AS parent_id,b.status AS parent_status,b.group_id,b.job_task,d.id AS detail_id,d.status,d.biz_no,d.onchain_business_id,d.biz_id,d.callback_result FROM onchain_biz_job_info b JOIN onchain_job_detail_info d ON d.biz_job_id=b.id AND d.is_deleted='N' WHERE b.group_id=%s AND b.job_task='SETTLEMENT_PROCESS' AND b.is_deleted='N' ORDER BY d.id","params":[inputs["from_task_id"]],"max_rows":3,"title":"限定本轮结算发起核心Mock任务回调"})
    if jobs["truncated"] or jobs["row_count"]>1:raise ValueError("结算发起任务范围不唯一")
    if after["truncated"] or after["row_count"]!=2 or [(r["id"],r["org_code"],str(r["status"])) for r in after["rows"]]!=[(inputs["from_task_id"],"000050","3"),(inputs["to_task_id"],"000053","3")]:raise ValueError("等待回调后双方任务状态不符，不重复审核")
    if not jobs or jobs["row_count"]!=1:raise ValueError("核心发起任务未唯一生成，保留现场不重提")
    job=jobs["rows"][0]
    ctx.log("本轮结算发起job只读结果="+str(job))
    if job["status"]!=8 or job["parent_status"]!=8 or job["callback_result"]!='{"code":"0"}' or job["biz_no"]!=inputs["settlement_no"] or job["onchain_business_id"]!=inputs["from_task_id"] or job["biz_id"]!="owned-local-settlement-tw-174791":raise ValueError("核心Mock任务未完成或映射不符，只能只读诊断，不重提审核")
    master=await ctx.call("tidb.query",{"sql":"SELECT id,settlement_no,biz_id,tx_id,total_amount,currency,from_org_code,to_org_code,busi_order_no FROM ri_settlement WHERE id=%s AND is_deleted='N'","params":[inputs["settlement_id"]],"max_rows":2,"title":"本轮结算发起Mock回写"})
    if master["truncated"] or master["row_count"]!=1:raise ValueError("结算主表不唯一")
    m=master["rows"][0]
    ctx.log("本轮结算主表只读结果="+str(m))
    if m["settlement_no"]!=inputs["settlement_no"] or m["biz_id"]!="owned-local-settlement-tw-174791" or m["tx_id"] is not None or str(m["total_amount"])!=inputs["expected_amount"] or m["currency"]!="SETTLE-CNY" or (m["from_org_code"],m["to_org_code"])!=("000050","000053") or m["busi_order_no"]:raise ValueError("发起回写或资金边界不符")
    return ctx.result(data={"settlement_id":inputs["settlement_id"],"settlement_no":inputs["settlement_no"],"from_task_id":inputs["from_task_id"],"to_task_id":inputs["to_task_id"],"normal_id":inputs["normal_id"],"run_label":inputs["run_label"],"role_states":after["rows"],"master":m,"core_mock_job":job,"sender_audit_completed":True,"verified_audited_only":verify_only,"receiver_confirmed":False,"submit_tx_id_missing":True,"mock_tx_contract_verified":False,"boundary":"本地发起审核、Mock任务及双方待确认；本轮旧Mock应答txId与消费tx不一致，发起tx_id为空且保留原证据，不证明交易/record；未接收方确认或资金接收"})
