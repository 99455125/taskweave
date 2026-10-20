async def run(ctx, inputs):
    number=inputs["platform_contract_number"]
    master=await ctx.call("tidb.query",{"sql":"SELECT id,treaty_name,org_business_code FROM ri_treaty_master WHERE id=%s AND cedent_treaty_no=%s AND org_business_code=%s AND is_deleted='N'","params":[inputs["master_id"],number,inputs["contract_suffix"]],"max_rows":2,"title":"第二次退回前冻结本轮V1主表"})
    if master["truncated"] or master["row_count"]!=1 or master["rows"][0]["treaty_name"]!=inputs["v2_treaty_name"]:raise ValueError("第二次退回前本轮主表或V1名称变化")
    states=await ctx.call("tidb.query",{"sql":"SELECT id,org_code,from_id,status,reviewer,biz_id FROM ri_treaty_reinsurer WHERE cedent_treaty_no=%s AND is_deleted='N' ORDER BY id","params":[number],"max_rows":4,"title":"第二次退回前本轮三方任务"})
    expected=[(inputs["cedant_id"],"000050",None,"3"),(inputs["source_id"],"000045",inputs["cedant_id"],"3")]
    if states["truncated"] or states["row_count"]!=2 or [(r["id"],r["org_code"],r["from_id"],str(r["status"])) for r in states["rows"]]!=expected:raise ValueError("第二次退回前任务阶段或上下游不符，不重复退回")
    if states["rows"][1]["biz_id"]!=inputs["expected_biz_id"] or states["rows"][1]["reviewer"] not in [None,"","000045"]:raise ValueError("退回任务业务或领取归属变化")
    previous=await ctx.call("tidb.query",{"sql":"SELECT id,SHA2(back_up_data,256) AS snapshot_sha256 FROM t_business_back_up_data WHERE source_table=2 AND source_id=%s AND is_deleted='N' ORDER BY id","params":[inputs["source_id"]],"max_rows":2,"title":"二次退回前仍保留V1快照"})
    if previous["truncated"] or previous["row_count"]!=1 or previous["rows"][0]["id"]!=inputs["snapshot_id"] or previous["rows"][0]["snapshot_sha256"]!=inputs["snapshot_sha256"]:raise ValueError("二次退回前旧快照已变化或本轮已经再次退回，停止重提")
    await ctx.call("playwright.page_open",{"url":"http://localhost:9877/TreatyManagement/Treaty","role":"reinsurer"})
    await ctx.call("playwright.page_assert_state",{"selector":"#查询条件_treatyCode","expected":{"count":1,"visible":True},"role":"reinsurer"})
    await ctx.call("playwright.page_fill",{"selector":"#查询条件_treatyCode","value":number,"role":"reinsurer"})
    button={"kind":"role","value":"button","name":"查 询","exact":True}
    await ctx.call("playwright.page_assert_state",{"selector":button,"expected":{"count":1,"visible":True,"enabled":True},"role":"reinsurer"})
    await ctx.call("playwright.page_click",{"selector":button,"role":"reinsurer"})
    tab={"kind":"role","value":"tab","name":"我的任务","exact":False}
    await ctx.call("playwright.page_assert_state",{"selector":tab,"expected":{"count":1,"enabled":True},"role":"reinsurer"})
    await ctx.call("playwright.page_click",{"selector":tab,"role":"reinsurer"})
    card='div[class*="list-item_"]:has(a:text-is("平台合约编号：'+number+'"))'
    await ctx.call("playwright.page_assert_state",{"selector":card,"expected":{"count":1,"visible":True},"role":"reinsurer"})
    process={"kind":"role","value":"button","name":"处 理","exact":True,"within":{"kind":"css","value":card}}
    await ctx.call("playwright.page_assert_state",{"selector":process,"expected":{"count":1,"enabled":True},"role":"reinsurer"})
    await ctx.call("playwright.page_click",{"selector":process,"role":"reinsurer"})
    await ctx.call("playwright.page_assert_text",{"selector":"body","text":"用户名称000045","role":"reinsurer"})
    await ctx.call("playwright.page_assert_url",{"url":"**/TreatyManagement/Treaty/entry?**cedentTreatyNo="+number+"&**id="+str(inputs["source_id"])+"&**","role":"reinsurer"})
    await ctx.call("playwright.page_assert_value",{"selector":"#treatyName","value":inputs["v2_input_suffix"],"role":"reinsurer"})
    name=await ctx.call("playwright.page_input_value",{"selector":"#treatyName","role":"reinsurer"})
    if name["value"]!=inputs["v2_input_suffix"]:raise ValueError("退回页面不是预期V2")
    decision={"kind":"label","value":"退回至分出人","exact":True}
    await ctx.call("playwright.page_check",{"selector":decision,"checked":True,"role":"reinsurer"})
    await ctx.call("playwright.page_assert_checked",{"selector":decision,"checked":True,"role":"reinsurer"})
    reason="仅供本地自测 "+inputs["contract_suffix"]+" 再保人退回分出方 V2"
    await ctx.call("playwright.page_fill",{"selector":"#comments","value":reason,"role":"reinsurer"})
    await ctx.call("playwright.page_assert_value",{"selector":"#comments","value":reason,"role":"reinsurer"})
    await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":"reinsurer"})
    await ctx.call("playwright.page_assert_url",{"url":"http://localhost:9877/TreatyManagement/Treaty","role":"reinsurer"})
    after=await ctx.call("tidb.query",{"sql":"SELECT id,org_code,from_id,status,biz_id FROM ri_treaty_reinsurer WHERE cedent_treaty_no=%s AND is_deleted='N' ORDER BY id","params":[number],"max_rows":4,"title":"第二次退回后分出方13再保人4直连双方"})
    expected=[(inputs["cedant_id"],"000050",None,"13"),(inputs["source_id"],"000045",inputs["cedant_id"],"4")]
    if after["truncated"] or after["row_count"]!=2 or [(r["id"],r["org_code"],r["from_id"],str(r["status"])) for r in after["rows"]]!=expected:raise ValueError("退回后状态不符，保留现场，不重提退回")
    backups=await ctx.call("tidb.query",{"sql":"SELECT id,source_table,source_id,is_deleted,SHA2(back_up_data,256) AS snapshot_sha256,JSON_UNQUOTE(JSON_EXTRACT(back_up_data,'$.riTreatyMasterDTO.treatyName')) AS frozen_name FROM t_business_back_up_data WHERE source_table=2 AND source_id=%s ORDER BY id","params":[inputs["source_id"]],"max_rows":3,"title":"第二次退回替换旧快照并冻结V2"})
    if backups["truncated"] or backups["row_count"]!=2:raise ValueError("二次退回未生成恰好两版快照，先诊断不重提")
    old,new=backups["rows"]
    if old["id"]!=inputs["snapshot_id"] or old["is_deleted"]!="Y" or old["snapshot_sha256"]!=inputs["snapshot_sha256"] or new["id"]<=old["id"] or new["is_deleted"]!="N" or not new["snapshot_sha256"] or new["snapshot_sha256"]==old["snapshot_sha256"] or new["frozen_name"]!=inputs["v2_treaty_name"]:raise ValueError("旧快照逻辑删除或新V2冻结内容不符，不重提退回")
    return ctx.result(data={"platform_contract_number":number,"contract_suffix":inputs["contract_suffix"],"source_table":2,"source_id":inputs["source_id"],"snapshots":backups["rows"],"snapshot_id":new["id"],"snapshot_sha256":new["snapshot_sha256"],"v2_treaty_name":new["frozen_name"],"reason":reason,"participants_after":after["rows"],"second_rejection_performed":True,"boundary":"正常UI第二次退回及本地精确Mock；旧Y新N且唯一有效V2，真实链record未验证"})
