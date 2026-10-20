async def run(ctx, inputs):
    number=inputs["platform_contract_number"]
    master=await ctx.call("tidb.query",{"sql":"SELECT id,treaty_name,org_business_code FROM ri_treaty_master WHERE id=%s AND cedent_treaty_no=%s AND org_business_code=%s AND is_deleted='N'","params":[inputs["master_id"],number,inputs["contract_suffix"]],"max_rows":2,"title":"首次退回前冻结本轮V1主表"})
    if master["truncated"] or master["row_count"]!=1 or master["rows"][0]["treaty_name"]!=inputs["expected_treaty_name"]:raise ValueError("首次退回前本轮主表或V1名称变化")
    states=await ctx.call("tidb.query",{"sql":"SELECT id,org_code,from_id,status,reviewer,biz_id FROM ri_treaty_reinsurer WHERE cedent_treaty_no=%s AND is_deleted='N' ORDER BY id","params":[number],"max_rows":4,"title":"首次退回前本轮三方任务"})
    expected=[(inputs["cedant_id"],"000050",None,"3"),(inputs["source_id"],"000053",inputs["cedant_id"],"3"),(inputs["reinsurer_id"],"000045",inputs["source_id"],"0")]
    if states["truncated"] or states["row_count"]!=3 or [(r["id"],r["org_code"],r["from_id"],str(r["status"])) for r in states["rows"]]!=expected:raise ValueError("首次退回前任务阶段或上下游不符，不重复退回")
    if states["rows"][1]["biz_id"]!=inputs["expected_biz_id"] or states["rows"][1]["reviewer"] not in [None,"","000053"]:raise ValueError("退回任务业务或领取归属变化")
    previous=await ctx.call("tidb.query",{"sql":"SELECT id,is_deleted FROM t_business_back_up_data WHERE source_table=2 AND source_id=%s ORDER BY id","params":[inputs["source_id"]],"max_rows":2,"title":"本轮首次退回前不得已有快照"})
    if previous["truncated"] or previous["row_count"]:raise ValueError("本轮已有退回快照，停止首次退回以核对原运行")
    await ctx.call("playwright.page_assert_text",{"selector":"body","text":"用户名称000053","role":"broker"})
    await ctx.call("playwright.page_assert_url",{"url":"**/TreatyManagement/Treaty/entry?**cedentTreatyNo="+number+"&**id="+str(inputs["source_id"])+"&**","role":"broker"})
    name=await ctx.call("playwright.page_input_value",{"selector":"#treatyName","role":"broker"})
    if name["value"]!=inputs["contract_suffix"]:raise ValueError("退回页面不是预期V1")
    decision={"kind":"label","value":"退回至分出人","exact":True}
    await ctx.call("playwright.page_check",{"selector":decision,"checked":True,"role":"broker"})
    await ctx.call("playwright.page_assert_checked",{"selector":decision,"checked":True,"role":"broker"})
    reason="仅供本地自测 "+inputs["contract_suffix"]+" 经纪退回分出方 V1"
    await ctx.call("playwright.page_fill",{"selector":"#comments","value":reason,"role":"broker"})
    await ctx.call("playwright.page_assert_value",{"selector":"#comments","value":reason,"role":"broker"})
    await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":"broker"})
    await ctx.call("playwright.page_assert_url",{"url":"http://localhost:9877/TreatyManagement/Treaty","role":"broker"})
    after=await ctx.call("tidb.query",{"sql":"SELECT id,org_code,from_id,status,biz_id FROM ri_treaty_reinsurer WHERE cedent_treaty_no=%s AND is_deleted='N' ORDER BY id","params":[number],"max_rows":4,"title":"首次退回后分出方13经纪4下游0"})
    expected=[(inputs["cedant_id"],"000050",None,"13"),(inputs["source_id"],"000053",inputs["cedant_id"],"4"),(inputs["reinsurer_id"],"000045",inputs["source_id"],"0")]
    if after["truncated"] or after["row_count"]!=3 or [(r["id"],r["org_code"],r["from_id"],str(r["status"])) for r in after["rows"]]!=expected:raise ValueError("退回后状态不符，保留现场，不重提退回")
    backup=await ctx.call("tidb.query",{"sql":"SELECT id,source_table,source_id,SHA2(back_up_data,256) AS snapshot_sha256 FROM t_business_back_up_data WHERE source_table=2 AND source_id=%s AND is_deleted='N' ORDER BY id","params":[inputs["source_id"]],"max_rows":2,"title":"首次退回来源2唯一有效快照"})
    if backup["truncated"] or backup["row_count"]!=1 or not backup["rows"][0]["snapshot_sha256"]:raise ValueError("首次退回未生成唯一快照，先诊断不重提")
    return ctx.result(data={"platform_contract_number":number,"contract_suffix":inputs["contract_suffix"],"master_id":inputs["master_id"],"source_table":2,"source_id":inputs["source_id"],"snapshot":backup["rows"][0],"v1_treaty_name":master["rows"][0]["treaty_name"],"v1_input_suffix":name["value"],"reason":reason,"participants_after":after["rows"],"rejection_performed":True,"boundary":"正常UI退回和本地精确REJECT Mock；真实链record未验证"})
