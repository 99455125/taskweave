async def run(ctx, inputs):
    result=await ctx.call("tidb.query",{"sql":"SELECT id,source_table,source_id,SHA2(back_up_data,256) AS snapshot_sha256,JSON_UNQUOTE(JSON_EXTRACT(back_up_data,'$.riTreatyMasterDTO.treatyName')) AS frozen_name,JSON_UNQUOTE(JSON_EXTRACT(back_up_data,'$.riTreatyMasterDTO.cedentTreatyNo')) AS frozen_number FROM t_business_back_up_data WHERE source_table=%s AND source_id=%s AND is_deleted='N' ORDER BY id","params":[inputs["source_table"],inputs["source_id"]],"max_rows":2,"title":"第二次退回唯一有效V2快照及内容"})
    if result["truncated"] or result["row_count"]!=1:raise ValueError("二次退回有效快照不唯一")
    row=result["rows"][0]
    if row["id"]!=inputs["expected_snapshot_id"] or row["snapshot_sha256"]!=inputs["expected_snapshot_sha256"] or row["frozen_name"]!=inputs["v2_treaty_name"] or row["frozen_number"]!=inputs["platform_contract_number"]:raise ValueError("二次退回V2快照归属或内容不符")
    party=await ctx.call("tidb.query",{"sql":"SELECT id,org_code,from_id,status,biz_id FROM ri_treaty_reinsurer WHERE id=%s AND cedent_treaty_no=%s AND is_deleted='N'","params":[inputs["source_id"],inputs["platform_contract_number"]],"max_rows":2,"title":"再保人退回详情任务状态与归属"})
    if party["truncated"] or party["row_count"]!=1 or party["rows"][0]["org_code"]!="000045" or party["rows"][0]["from_id"]!=inputs["cedant_id"] or str(party["rows"][0]["status"])!="4" or party["rows"][0]["biz_id"]!=inputs["expected_biz_id"]:raise ValueError("当前不在本轮再保人退回详情阶段")
    await ctx.call("playwright.page_assert_text",{"selector":"body","text":"用户名称000045","role":"reinsurer"})
    await ctx.call("playwright.page_open",{"url":"http://localhost:9877/TreatyManagement/Treaty","role":"reinsurer"})
    await ctx.call("playwright.page_assert_state",{"selector":"#查询条件_treatyCode","expected":{"count":1,"visible":True},"role":"reinsurer"})
    await ctx.call("playwright.page_fill",{"selector":"#查询条件_treatyCode","value":inputs["platform_contract_number"],"role":"reinsurer"})
    button={"kind":"role","value":"button","name":"查 询","exact":True}
    await ctx.call("playwright.page_assert_state",{"selector":button,"expected":{"count":1,"enabled":True},"role":"reinsurer"})
    await ctx.call("playwright.page_click",{"selector":button,"role":"reinsurer"})
    tab={"kind":"role","value":"tab","name":"全部","exact":False}
    await ctx.call("playwright.page_assert_state",{"selector":tab,"expected":{"count":1,"enabled":True},"role":"reinsurer"})
    await ctx.call("playwright.page_click",{"selector":tab,"role":"reinsurer"})
    card='div[class*="list-item_"]:has(a:text-is("平台合约编号：'+inputs["platform_contract_number"]+'"))'
    await ctx.call("playwright.page_assert_state",{"selector":card,"expected":{"count":1,"visible":True},"role":"reinsurer"})
    link={"kind":"css","value":'a:text-is("平台合约编号：'+inputs["platform_contract_number"]+'")',"within":{"kind":"css","value":card}}
    await ctx.call("playwright.page_assert_state",{"selector":link,"expected":{"count":1,"visible":True},"role":"reinsurer"})
    await ctx.call("playwright.page_click",{"selector":link,"role":"reinsurer"})
    await ctx.call("playwright.page_assert_url",{"url":"**/TreatyManagement/Treaty/view?**cedentTreatyNo="+inputs["platform_contract_number"]+"&**id="+str(inputs["source_id"])+"&**","role":"reinsurer"})
    await ctx.call("playwright.page_assert_value",{"selector":"#treatyName","value":inputs["v2_input_suffix"],"role":"reinsurer"})
    await ctx.call("playwright.page_assert_state",{"selector":"#treatyName","expected":{"count":1,"editable":False},"role":"reinsurer"})
    value=await ctx.call("playwright.page_input_value",{"selector":"#treatyName","role":"reinsurer"})
    return ctx.result(data={"snapshot_id":row["id"],"snapshot_sha256":row["snapshot_sha256"],"source_table":row["source_table"],"source_id":row["source_id"],"platform_contract_number":inputs["platform_contract_number"],"frozen_name":row["frozen_name"],"receiver_view_suffix":value["value"],"second_version_readonly_view_verified":True,"boundary":"本轮独立再保人退回流程分段完成；真实record与全新会话整套运行未验证"})
