async def run(ctx, inputs):
    role="cedant"
    existing=await ctx.call("tidb.query",{"sql":"SELECT id,record_no,statement_status,comment FROM ri_statement WHERE input_org_code='000050' AND treaty_id=%s AND (comment=%s OR id=%s) AND is_deleted='N' ORDER BY id","params":[inputs["treaty_master_id"],"仅供本地自测 "+inputs["bill_label"],inputs.get("expected_unsaved_draft_id")],"max_rows":2,"title":"本轮总账单创建前核对"})
    if existing["truncated"] or existing["row_count"]>1:raise ValueError("本轮合约的总账单前置不唯一，停止新建")
    if existing["row_count"]==1:
        owned=existing["rows"][0]
        if owned["comment"]!="仅供本地自测 "+inputs["bill_label"]:
            if owned["comment"] or inputs.get("expected_unsaved_draft_id")!=owned["id"]:
                raise ValueError("同合约已有其他轮次草稿，未证明本轮归属，不覆盖。未保存草稿须按原创建run明确提供ID。")
    if existing["row_count"]==0:
        unmarked=await ctx.call("tidb.query",{"sql":"SELECT id FROM ri_statement WHERE input_org_code='000050' AND treaty_id=%s AND statement_status=0 AND (comment IS NULL OR comment='') AND is_deleted='N' ORDER BY id","params":[inputs["treaty_master_id"]],"max_rows":2,"title":"创建前未归属草稿保护"})
        if unmarked["truncated"] or unmarked["row_count"]:raise ValueError("同合约存在未标识草稿，先按原创建证据恢复；不重复新建或接管")
        watermark=await ctx.call("tidb.query",{"sql":"SELECT MAX(id) AS max_id FROM ri_statement WHERE input_org_code='000050' AND treaty_id=%s","params":[inputs["treaty_master_id"]],"max_rows":1,"title":"本轮新增前账单主键水位"})
        after_id=watermark["rows"][0]["max_id"] or 0
        modal={"kind":"role","value":"dialog","name":"账单类型","exact":True}
        type_open=await ctx.call("playwright.page_state",{"selector":modal,"role":role})
        if type_open["match_count"]==0:
            drawer={"kind":"css","value":".bill-page-drawer"}
            opened=await ctx.call("playwright.page_state",{"selector":drawer,"role":role})
            if opened["match_count"]==0:
                await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"新增合约账单","exact":True},"role":role})
            await ctx.call("playwright.page_assert_state",{"selector":drawer,"expected":{"count":1,"visible":True},"role":role})
            field={"kind":"label","value":"平台或机构合约编号","exact":True,"within":drawer}
            await ctx.call("playwright.page_fill",{"selector":field,"value":inputs["platform_treaty_no"],"role":role})
            await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"查 询","exact":True,"within":drawer},"role":role})
            row={"kind":"role","value":"row","name":inputs["platform_treaty_no"],"exact":False,"within":drawer}
            await ctx.call("playwright.page_assert_state",{"selector":row,"expected":{"count":1,"visible":True},"role":role})
            select={"kind":"role","value":"radio","within":row}
            await ctx.call("playwright.page_check",{"selector":select,"checked":True,"role":role})
            await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"确 认","exact":True,"within":drawer},"role":role})
            await ctx.call("playwright.page_assert_state",{"selector":modal,"expected":{"count":1,"visible":True},"role":role})
        state=await ctx.call("playwright.page_attribute",{"selector":"#billType","name":"aria-expanded","role":role})
        if state["value"]!="true":
            await ctx.call("playwright.page_click",{"selector":"#billType >> xpath=ancestor::div[1]","role":role})
        await ctx.call("playwright.page_click",{"selector":"text=定期账单","role":role})
        total={"kind":"label","value":"总账单","exact":True,"within":modal}
        await ctx.call("playwright.page_assert_state",{"selector":total,"expected":{"count":1,"enabled":True},"role":role})
        await ctx.call("playwright.page_check",{"selector":total,"checked":True,"role":role})
        await ctx.call("playwright.page_assert_checked",{"selector":total,"checked":True,"role":role})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"确 定","exact":True,"within":modal},"role":role})
        await ctx.call("playwright.page_assert_url",{"url":"**/ContractBill/list/add?**","role":role})
    if existing["row_count"]==0:
        rows=await ctx.call("tidb.query",{"sql":"SELECT id,record_no,statement_status,bill_type,statement_flag FROM ri_statement WHERE input_org_code='000050' AND treaty_id=%s AND id>%s AND is_deleted='N' ORDER BY id","params":[inputs["treaty_master_id"],after_id],"max_rows":2,"title":"本轮新建总账单草稿回读"})
    else:
        rows=await ctx.call("tidb.query",{"sql":"SELECT id,record_no,statement_status,bill_type,statement_flag FROM ri_statement WHERE input_org_code='000050' AND treaty_id=%s AND id=%s AND is_deleted='N'","params":[inputs["treaty_master_id"],existing["rows"][0]["id"]],"max_rows":2,"title":"本轮已归属总账单草稿回读"})
    if rows["truncated"] or rows["row_count"]!=1:raise ValueError("新增总账单应恰好1条")
    draft=rows["rows"][0]
    if draft["statement_status"]!=0 or draft["bill_type"]!=1 or draft["statement_flag"]!=1:raise ValueError("本轮账单不是定期总账单草稿，不重复创建或覆盖")
    if existing["row_count"]==0:
        ctx.log("本轮新建总账单草稿ID="+str(draft["id"])+"，案卷号="+draft["record_no"]+"；中断恢复可按本运行证据提供expected_unsaved_draft_id")
    await ctx.call("playwright.page_assert_url",{"url":"**/ContractBill/list/add?**id="+str(draft["id"])+"&**","role":role})
    await ctx.call("playwright.page_assert_value",{"selector":"#cedentTreatyNo","value":inputs["platform_treaty_no"],"role":role})
    async def choose_date(value):
        if len(value)!=10 or value[4]!="-" or value[7]!="-" or not value.replace("-", "").isdigit():raise ValueError("账单日期格式不正确")
        target=int(value[:4])*12+int(value[5:7])
        cell=".ant-picker-dropdown:not(.ant-picker-dropdown-hidden) td.ant-picker-cell-in-view[title='"+value+"']"
        for calendar_attempt in range(24):
            state=await ctx.call("playwright.page_state",{"selector":cell,"role":role})
            if state["match_count"]==1 and state["visible"]:
                await ctx.call("playwright.page_click",{"selector":cell,"role":role})
                return
            years=await ctx.call("playwright.page_list",{"selector":".ant-picker-dropdown:not(.ant-picker-dropdown-hidden) .ant-picker-year-btn","role":role})
            months=await ctx.call("playwright.page_list",{"selector":".ant-picker-dropdown:not(.ant-picker-dropdown-hidden) .ant-picker-month-btn","role":role})
            if years["total_count"]!=2 or months["total_count"]!=2:raise ValueError("账单日期面板不是实际双月视图")
            shown=[int(years["items"][i]["text"].replace("年", ""))*12+int(months["items"][i]["text"].replace("月", "")) for i in range(2)]
            if min(shown)<=target<=max(shown):
                await ctx.call("playwright.page_assert_state",{"selector":cell,"expected":{"count":1,"visible":True},"role":role})
                await ctx.call("playwright.page_click",{"selector":cell,"role":role})
                return
            button=".ant-picker-header-prev-btn" if target<min(shown) else ".ant-picker-header-next-btn"
            await ctx.call("playwright.page_click",{"selector":".ant-picker-dropdown:not(.ant-picker-dropdown-hidden) "+button+":visible","role":role})
        raise ValueError("账单日期超出本次有限日历翻页范围")
    await ctx.call("playwright.page_click",{"selector":"#statementDate","role":role})
    await choose_date(inputs["statement_start_date"])
    await choose_date(inputs["statement_end_date"])
    end={"kind":"css","value":"input[placeholder='结束日期']","within":{"kind":"css","value":"#statementDate >> xpath=ancestor::div[2]"}}
    await ctx.call("playwright.page_assert_value",{"selector":"#statementDate","value":inputs["statement_start_date"],"role":role})
    await ctx.call("playwright.page_assert_value",{"selector":end,"value":inputs["statement_end_date"],"role":role})
    await ctx.call("playwright.page_fill",{"selector":"#accountPeriod","value":inputs["account_period"],"role":role})
    await ctx.call("playwright.page_assert_value",{"selector":"#accountPeriod","value":inputs["account_period"],"role":role})
    tax={"kind":"label","value":"是","exact":True,"within":{"kind":"css","value":"#taxFreeFlag"}}
    await ctx.call("playwright.page_check",{"selector":tax,"checked":True,"role":role})
    await ctx.call("playwright.page_assert_checked",{"selector":tax,"checked":True,"role":role})
    await ctx.call("playwright.page_fill",{"selector":"#comment","value":"仅供本地自测 "+inputs["bill_label"],"role":role})
    await ctx.call("playwright.page_assert_value",{"selector":"#comment","value":"仅供本地自测 "+inputs["bill_label"],"role":role})
    return ctx.result(data={"statement_id":draft["id"],"record_no":draft["record_no"],"platform_treaty_no":inputs["platform_treaty_no"],"treaty_master_id":inputs["treaty_master_id"],"bill_label":inputs["bill_label"],"cedent_statement_numbers":inputs["cedent_statement_numbers"],"bill_type":"定期账单","statement_flag":"总账单","period":[inputs["statement_start_date"],inputs["statement_end_date"]],"base_fields_persisted":False,"boundary":"已创建唯一总账单草稿，基本字段页面回读一致；项目录入、试算、完整保存由下一步完成。"})
