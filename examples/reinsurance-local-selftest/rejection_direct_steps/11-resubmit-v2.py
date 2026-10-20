async def run(ctx, inputs):
    number=inputs["platform_contract_number"]
    verify_only=inputs.get("verify_submitted_only",False)
    master=await ctx.call("tidb.query",{"sql":"SELECT id,treaty_name,org_business_code FROM ri_treaty_master WHERE id=%s AND cedent_treaty_no=%s AND org_business_code=%s AND is_deleted='N'","params":[inputs["master_id"],number,inputs["contract_suffix"]],"max_rows":2,"title":"重提前本轮V2主表守卫"})
    if master["truncated"] or master["row_count"]!=1 or master["rows"][0]["treaty_name"]!=inputs["v2_treaty_name"]:raise ValueError("本轮V2主表或归属变化")
    async def states(completed):
        r=await ctx.call("tidb.query",{"sql":"SELECT id,org_code,from_id,status,biz_id FROM ri_treaty_reinsurer WHERE cedent_treaty_no=%s AND is_deleted='N' ORDER BY id","params":[number],"max_rows":4,"title":"重提前后本轮三方状态"})
        expected=[(inputs["cedant_id"],"000050",None,"3" if completed else "13"),(inputs["source_id"],"000045",inputs["cedant_id"],"3" if completed else "4")]
        if r["truncated"] or r["row_count"]!=2 or [(x["id"],x["org_code"],x["from_id"],str(x["status"])) for x in r["rows"]]!=expected or r["rows"][1]["biz_id"]!=inputs["expected_biz_id"]:raise ValueError("重提阶段、上下游或业务ID不符，先核对原运行")
        return r["rows"]
    async def snapshot():
        r=await ctx.call("tidb.query",{"sql":"SELECT id,SHA2(back_up_data,256) AS snapshot_sha256 FROM t_business_back_up_data WHERE source_table=2 AND source_id=%s AND is_deleted='N' ORDER BY id","params":[inputs["source_id"]],"max_rows":2,"title":"重提必须保留首次退回快照"})
        if r["truncated"] or r["row_count"]!=1 or r["rows"][0]["id"]!=inputs["snapshot_id"] or r["rows"][0]["snapshot_sha256"]!=inputs["snapshot_sha256"]:raise ValueError("重提旧快照已变或丢失")
        return r["rows"][0]
    await states(verify_only)
    await snapshot()
    jobs=await ctx.call("tidb.query",{"sql":"SELECT id,status FROM onchain_biz_job_info WHERE group_id=%s AND biz_no=%s AND job_task='TREATY_PROCESS' AND is_deleted='N' ORDER BY id","params":[inputs["cedant_id"],number],"max_rows":3,"title":"首次提交基线及重提次数守卫"})
    if jobs["truncated"] or jobs["row_count"]!=(2 if verify_only else 1) or jobs["rows"][0]["id"]!=inputs["before_job_id"] or jobs["rows"][0]["status"]!=8:raise ValueError("重提核心任务已存在或首次基线不符，不再提交")
    if not verify_only:
        await ctx.call("playwright.page_assert_text",{"selector":"body","text":"用户名称000050","role":"cedant"})
        await ctx.call("playwright.page_assert_url",{"url":"**/TreatyManagement/Treaty/cendentrollback?**cedentTreatyNo="+number+"&**id="+str(inputs["cedant_id"])+"&**","role":"cedant"})
        await ctx.call("playwright.page_assert_value",{"selector":"#orgBusinessCode","value":inputs["contract_suffix"],"role":"cedant"})
        await ctx.call("playwright.page_assert_value",{"selector":"#treatyName","value":inputs["v2_input_suffix"],"role":"cedant"})
        watermark=await ctx.call("tidb.query",{"sql":"SELECT MAX(id) AS max_id FROM t_ri_gsc_onchain_record","max_rows":1,"title":"本轮重提前record水位"})
        if watermark["truncated"] or watermark["row_count"]!=1:raise ValueError("重提前record水位读取异常")
        ctx.log("本轮V2重提前record水位="+str(watermark["rows"][0]["max_id"]))
        decision={"kind":"label","value":"本公司确认并提交至对手方","exact":True}
        await ctx.call("playwright.page_check",{"selector":decision,"checked":True,"role":"cedant"})
        await ctx.call("playwright.page_fill",{"selector":"#comments","value":"仅供本地自测 "+inputs["contract_suffix"]+" V2重提","role":"cedant"})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":"cedant"})
        await ctx.call("playwright.page_assert_url",{"url":"http://localhost:9877/TreatyManagement/Treaty","role":"cedant"})
    waiting=await ctx.call("process.run",{"executable":"/Users/xiaojuju/Projects/company/bjs/dev-environment/imports/verify-venv/bin/python","args":["/Users/xiaojuju/Projects/company/bjs/dev-environment/test-support/wait_owned_direct_treaty_resubmit.py","--phase","resubmit","--before-job",str(inputs["before_job_id"]),"--attempt","2"],"timeout_seconds":45,"max_output_bytes":65536})
    ctx.log("本轮独立重提只读等待="+waiting["stdout"])
    if waiting["exit_code"]!=0 or waiting["stdout_truncated"] or waiting["stderr_truncated"]:raise ValueError("重提仍在处理或回调检查异常；保留新任务状态，不重复提交或恢复")
    after=await states(True)
    unchanged=await snapshot()
    new=await ctx.call("tidb.query",{"sql":"SELECT b.id AS parent_id,b.status AS parent_status,d.id AS detail_id,d.status,d.biz_id,d.callback_result,d.onchain_times FROM onchain_biz_job_info b JOIN onchain_job_detail_info d ON d.biz_job_id=b.id AND d.is_deleted='N' WHERE b.group_id=%s AND b.biz_no=%s AND b.job_task='TREATY_PROCESS' AND b.id>%s AND b.is_deleted='N' ORDER BY b.id,d.id","params":[inputs["cedant_id"],number,inputs["before_job_id"]],"max_rows":2,"title":"只核对本次新建重提任务"})
    if new["truncated"] or new["row_count"]!=1 or new["rows"][0]["parent_status"]!=8 or new["rows"][0]["status"]!=8 or new["rows"][0]["biz_id"]!=inputs["expected_biz_id"] or new["rows"][0]["callback_result"]!='{"code":"0"}':raise ValueError("新重提任务或回调不唯一成功")
    return ctx.result(data={"platform_contract_number":number,"contract_suffix":inputs["contract_suffix"],"source_table":2,"source_id":inputs["source_id"],"participants":after,"snapshot":unchanged,"new_core_mock_job":new["rows"][0],"before_job_id":inputs["before_job_id"],"v2_treaty_name":inputs["v2_treaty_name"],"resubmitted":True,"verified_submitted_only":verify_only,"boundary":"正常UI重提及本地精确Mock回调；旧快照仍保留，真实record另验收"})
