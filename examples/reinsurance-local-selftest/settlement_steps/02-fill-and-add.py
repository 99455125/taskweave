async def run(ctx, inputs):
    role=inputs["role"]
    guard=await ctx.call("tidb.query",{"sql":"SELECT s.id,s.institution_settlement_no,s.comments,s.currency,s.from_org_code,s.to_org_code,r.status FROM ri_settlement s JOIN ri_settlement_reinsurer r ON r.settlement_no=s.settlement_no AND r.id=%s AND r.is_deleted='N' WHERE s.id=%s AND s.settlement_no=%s AND s.is_deleted='N'","params":[inputs["from_task_id"],inputs["settlement_id"],inputs["settlement_no"]],"max_rows":2,"title":"保存前本轮结算守卫"})
    if guard["truncated"] or guard["row_count"]!=1:raise ValueError("结算主从关联不唯一")
    s=guard["rows"][0]
    if (s["currency"],s["from_org_code"],s["to_org_code"],str(s["status"]))!=("SETTLE-CNY","000050","000053","0") or s["institution_settlement_no"] not in [None,"",inputs["run_label"]] or s["comments"] not in [None,"","仅供本地自测 "+inputs["run_label"]]:raise ValueError("结算状态、归属或本轮备注变化")
    old=await ctx.call("tidb.query",{"sql":"SELECT id FROM ri_settlement_statement WHERE settlement_no=%s AND is_deleted='N'","params":[inputs["settlement_no"]],"max_rows":2,"title":"保存前禁止重复明细"})
    if old["truncated"] or (old["row_count"] and not inputs["verify_saved_only"]):raise ValueError("已有明细，停止重复保存，请走只读重新打开步骤")
    if inputs["verify_saved_only"] and old["row_count"]!=1:raise ValueError("只读恢复要求已有唯一明细")
    if not inputs["verify_saved_only"]:
        await ctx.call("playwright.page_assert_value",{"selector":"#settlementNo","value":inputs["settlement_no"],"role":role})
        # S01 leaves an unsaved candidate selected. Close it to fill the base fields,
        # then choose the same exact candidate again before the single save action.
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"取 消","exact":True},"role":role})
        await ctx.call("playwright.page_fill",{"selector":"#institutionSettlementNo","value":inputs["run_label"],"role":role})
        await ctx.call("playwright.page_fill",{"selector":"#comments","value":"仅供本地自测 "+inputs["run_label"],"role":role})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"添加账单","exact":True},"role":role})
        await ctx.call("playwright.page_fill",{"selector":"#platformStatementNo","value":inputs["platform_statement_no"],"role":role})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"查 询","exact":True},"role":role})
        target='tr:has(a:text-is("'+inputs["platform_statement_no"]+'"))'
        await ctx.call("playwright.page_assert_state",{"selector":target,"expected":{"count":1,"visible":True},"role":role})
        await ctx.call("playwright.page_check",{"selector":target+' input[type="checkbox"]',"checked":True,"role":role})
        await ctx.call("playwright.page_assert_checked",{"selector":target+' input[type="checkbox"]',"checked":True,"role":role})
        # Drawer confirmation invokes the product's save endpoint; it is a real write.
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"确 定","exact":True},"role":role})
        await ctx.call("playwright.page_assert_state",{"selector":"#platformStatementNo","expected":{"count":0},"role":role})
        amount=await ctx.call("playwright.page_input_value",{"selector":"#totalAmount","role":role})
        if amount["value"].replace(",","")!=inputs["expected_amount"]:raise ValueError("结算页面汇总金额不符")
    saved=await ctx.call("tidb.query",{"sql":"SELECT s.id,s.institution_settlement_no,s.comments,s.total_amount,s.payer_org_code,s.receiver_org_code,d.id AS detail_id,d.statement_id,d.statement_normal_id,d.platform_statement_no,d.platform_statement_no_temp,d.statement_currency,d.statement_amount,d.settlement_amount,d.sign_chain_id,d.file_id FROM ri_settlement s JOIN ri_settlement_statement d ON d.settlement_no=s.settlement_no AND d.is_deleted='N' WHERE s.id=%s AND s.is_deleted='N'","params":[inputs["settlement_id"]],"max_rows":3,"title":"本轮结算保存与单一账单明细"})
    if saved["truncated"] or saved["row_count"]!=1:raise ValueError("保存结果不唯一或尚不可见；保留现场，不重复保存")
    r=saved["rows"][0]
    if r["institution_settlement_no"]!=inputs["run_label"] or r["comments"]!="仅供本地自测 "+inputs["run_label"] or (r["platform_statement_no"] or r["platform_statement_no_temp"])!=inputs["platform_statement_no"] or str(r["statement_normal_id"])!=str(inputs["normal_id"]) or r["statement_currency"]!="CNY" or any(str(r[k])!=inputs["expected_amount"] for k in ["total_amount","statement_amount"]) or r["payer_org_code"]!="000050" or r["receiver_org_code"]!="000053" or r["sign_chain_id"]!="owned-local-mock-sign-bill-257312" or r["file_id"]!="owned-local-pdf-ddfdea6f235bacf52923b856cda024c9e5b15fc8f5cb397135a109e522b3e662":raise ValueError("保存关键字段、金额或模拟单证引用不符")
    return ctx.result(data={"settlement_id":inputs["settlement_id"],"settlement_no":inputs["settlement_no"],"from_task_id":inputs["from_task_id"],"to_task_id":inputs["to_task_id"],"normal_id":inputs["normal_id"],"run_label":inputs["run_label"],"saved":r,"submitted":False,"verified_saved_only":inputs["verify_saved_only"],"detail_settlement_amount_persisted":r["settlement_amount"] is not None,"boundary":"真实页面添加账单确定触发保存；双签文件及链ID仅为本地Mock，不代表真实签名或资金调用"})
