async def run(ctx, inputs):
    role="cedant"
    owned=await ctx.call("tidb.query",{"sql":"SELECT id,treaty_id,record_no,statement_status,comment FROM ri_statement WHERE id=%s AND input_org_code='000050' AND is_deleted='N'","params":[inputs["statement_id"]],"max_rows":2,"title":"独立退回账单保存前归属"})
    if owned["truncated"] or owned["row_count"]!=1:raise ValueError("独立账单草稿不存在或不唯一")
    own=owned["rows"][0]
    if own["treaty_id"]!=inputs["treaty_master_id"] or own["record_no"]!=inputs["record_no"] or own["statement_status"]!=0 or own["comment"] not in [None,"","仅供本地自测 "+inputs["bill_label"]]:raise ValueError("独立退回账单归属或草稿阶段不符，停止保存")
    await ctx.call("playwright.page_assert_value",{"selector":"#comment","value":"仅供本地自测 "+inputs["bill_label"],"role":role})
    party=await ctx.call("tidb.query",{"sql":"SELECT id FROM ri_treaty_reinsurer WHERE cedent_treaty_no=%s AND org_code='000045' AND reinsurance_role='02' AND is_deleted='N'","params":[inputs["platform_treaty_no"]],"max_rows":2,"title":"本轮直连再保人控件前置"})
    if party["truncated"] or party["row_count"]!=1:raise ValueError("本轮直连再保人不唯一")
    reinsurer_party_id=party["rows"][0]["id"]
    await ctx.call("playwright.page_assert_url",{"url":"**/ContractBill/list/add?**id="+str(inputs["statement_id"])+"&**","role":role})
    panel={"kind":"css","value":"#rc-tabs-1-panel-1"}
    pending=await ctx.call("playwright.page_state",{"selector":{"kind":"role","value":"button","name":"确 定","exact":True},"role":role})
    if pending["match_count"]==1:
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"取 消","exact":True},"role":role})
    calculator={"kind":"css","value":"#rc-tabs-1-panel-1 > div:nth-of-type(1) > div:nth-of-type(1)"}
    fields=await ctx.call("playwright.page_state",{"selector":{"kind":"css","value":"input[id^='itemAmount-']","within":calculator},"role":role})
    if fields["match_count"]==0:
        await ctx.call("playwright.page_click",{"selector":"#rc-tabs-1-panel-1 > div:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(1)","role":role})
    currency={"kind":"css","value":"input[id$='-currency']","within":calculator}
    await ctx.call("playwright.page_assert_state",{"selector":currency,"expected":{"count":1,"visible":True,"enabled":True},"role":role})
    currency_control={"kind":"css","value":".ant-select:has(input[id$='-currency']) .ant-select-selector","within":calculator}
    await ctx.call("playwright.page_assert_state",{"selector":currency_control,"expected":{"count":1,"visible":True,"enabled":True},"role":role})
    await ctx.call("playwright.page_click",{"selector":currency_control,"role":role})
    await ctx.call("playwright.page_fill",{"selector":currency,"value":"CNY","role":role})
    option=".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option:has-text('CNY')"
    await ctx.call("playwright.page_assert_state",{"selector":option,"expected":{"count":1,"visible":True,"enabled":True},"role":role})
    await ctx.call("playwright.page_click",{"selector":option,"role":role})
    for item in inputs["total_items"]:
        row={"kind":"role","value":"row","name":item["name"],"exact":False,"within":calculator}
        amount={"kind":"css","value":"input[id^='itemAmount-']","within":row}
        await ctx.call("playwright.page_fill",{"selector":amount,"value":item["amount"],"role":role})
        await ctx.call("playwright.page_press",{"selector":amount,"key":"Tab","role":role})
    await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"试 算","exact":True,"within":calculator},"role":role})
    await ctx.call("playwright.page_assert_state",{"selector":{"kind":"role","value":"button","name":"确 定","exact":True},"expected":{"count":1,"visible":True},"role":role})
    await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"确 定","exact":True},"role":role})
    number="input[id$='-"+str(reinsurer_party_id)+"-cedentStatementNo']"
    state=await ctx.call("playwright.page_state",{"selector":number,"role":role})
    if state["match_count"]==0 or not state["visible"]:
        await ctx.call("playwright.page_click",{"selector":"#rc-tabs-1-panel-1 > div:nth-of-type(1) > div:nth-of-type(2) > div:nth-of-type(2) > div:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(1) > span:nth-of-type(1) > div:nth-of-type(1) > span:nth-of-type(1) > a:nth-of-type(1)","role":role})
    await ctx.call("playwright.page_fill",{"selector":number,"value":inputs["bill_label"]+"-TOTAL","role":role})
    await ctx.call("playwright.page_press",{"selector":number,"key":"Tab","role":role})
    await ctx.call("playwright.page_assert_value",{"selector":number,"value":inputs["bill_label"]+"-TOTAL","role":role})
    await ctx.call("playwright.page_wait",{"selector":".ant-notification-notice-success","state":"hidden","role":role})
    await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"保 存","exact":True},"role":role})
    await ctx.call("playwright.page_wait",{"selector":".ant-notification-notice-success","state":"visible","role":role})
    master=await ctx.call("tidb.query",{"sql":"SELECT id,record_no,statement_status,statement_start_date,statement_end_date,account_period,tax_free_flag,comment FROM ri_statement WHERE id=%s AND input_org_code='000050' AND is_deleted='N'","params":[inputs["statement_id"]],"max_rows":2,"title":"本轮账单保存基本信息"})
    normals=await ctx.call("tidb.query",{"sql":"SELECT id,statement_id,statement_flag,statement_status,treaty_reinsurer_id,currency,net_balance,cedent_statement_no,input_org_code,enter_org_code,parent_id FROM ri_statement_normal WHERE statement_id=%s AND is_deleted='N' ORDER BY id","params":[inputs["statement_id"]],"max_rows":10,"title":"本轮总账单试算保存结果"})
    if master["truncated"] or master["row_count"]!=1:raise ValueError("账单主表不唯一")
    saved=master["rows"][0]
    if saved["statement_status"]!=0 or saved["account_period"]!=inputs["account_period"] or saved["comment"]!="仅供本地自测 "+inputs["bill_label"]:raise ValueError("账单基础字段未正确保存")
    if str(saved["statement_start_date"])[:10]!=inputs["statement_start_date"] or str(saved["statement_end_date"])[:10]!=inputs["statement_end_date"]:raise ValueError("账单起止期未正确保存")
    rows=normals["rows"]
    if normals["truncated"] or normals["row_count"]!=1 or [(r["input_org_code"],r["enter_org_code"]) for r in rows]!=[("000050","000045")]:raise ValueError("总账单上下游关系不符")
    if any(r["statement_status"]!=0 or r["statement_flag"]!=1 or r["currency"]!="CNY" or str(r["net_balance"])!=inputs["expected_net_balance"] for r in rows):raise ValueError("总账单试算金额或草稿状态不符")
    if rows[0]["cedent_statement_no"]!=inputs["bill_label"]+"-TOTAL" or rows[0]["parent_id"] is not None:raise ValueError("总账单编号或父子关系不符")
    return ctx.result(data={"master":saved,"normals":rows,"base_fields_persisted":True,"total_items":inputs["total_items"],"boundary":"本地定期总账单试算并保存，直连单段总账单净额按本笔预期核对；可选分项账单未试算未保存，不计本次覆盖。尚未提交、审核、对手确认或上链。"})
