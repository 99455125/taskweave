async def run(ctx, inputs):
    number=inputs["platform_contract_number"]
    suffix=inputs["contract_suffix"]
    async def states():
        result=await ctx.call("tidb.query",{"sql":"SELECT id,org_code,reinsurance_role,from_id,status,review_level,reviewer,file_status,biz_id FROM ri_treaty_reinsurer WHERE cedent_treaty_no=%s AND is_deleted='N' ORDER BY id","params":[number],"max_rows":10,"title":"本轮合约参与方状态"})
        if result["truncated"] or result["row_count"]!=2:raise ValueError("本轮合约必须恰好两个参与方")
        rows=result["rows"]
        if [(r["org_code"],r["reinsurance_role"]) for r in rows]!=[("000050","01"),("000045","02")]:raise ValueError("参与方顺序或角色不符")
        if rows[1]["from_id"]!=rows[0]["id"]:raise ValueError("上下游关系不符")
        return rows
    before=await states()
    watermark_id=None
    already_submitted=before[1]["status"]=="3" and bool(before[1]["biz_id"])
    if already_submitted:
        watermark_id=inputs.get("recovery_watermark")
        if watermark_id is None:raise ValueError("已提交仅只读恢复，须提供原提交日志的record水位")
    if not already_submitted:
        if any(r["status"]!="0" for r in before):
            raise ValueError("提交前状态已发生变化，先核对原运行，不重复提交")
        existing=await ctx.call("tidb.query",{"sql":"SELECT id,status FROM onchain_biz_job_info WHERE group_id=%s AND biz_no=%s AND job_task='TREATY_PROCESS' AND is_deleted='N' ORDER BY id","params":[before[0]["id"],number],"max_rows":2,"title":"直连新合约避免重复提交"})
        if existing["truncated"] or existing["row_count"]:raise ValueError("直连核心任务已存在，不重复提交")
        watermark=await ctx.call("tidb.query",{"sql":"SELECT MAX(id) AS max_id FROM t_ri_gsc_onchain_record","max_rows":1,"title":"提交前record水位"})
        if watermark["truncated"] or watermark["row_count"]!=1:raise ValueError("record水位无法唯一读取")
        watermark_id=watermark["rows"][0]["max_id"]
        ctx.log("直连新合约提交前record水位="+str(watermark_id))
        await ctx.call("playwright.page_assert_url",{"url":"**/TreatyManagement/Treaty/edit?**cedentTreatyNo="+number+"&**","role":"cedant"})
        await ctx.call("playwright.page_assert_value",{"selector":"#orgBusinessCode","value":suffix,"role":"cedant"})
        choice={"kind":"label","value":"本公司确认并提交至对手方","exact":True}
        await ctx.call("playwright.page_check",{"selector":choice,"checked":True,"role":"cedant"})
        comment="仅供本地自测 "+suffix+" 分出方发起"
        await ctx.call("playwright.page_fill",{"selector":"#comments","value":comment,"role":"cedant"})
        await ctx.call("playwright.page_assert_value",{"selector":"#comments","value":comment,"role":"cedant"})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":"cedant"})
        await ctx.call("playwright.page_assert_url",{"url":"**/TreatyManagement/Treaty","role":"cedant"})
        watermark_id=watermark["rows"][0]["max_id"]
    # Resuming a successful external effect only reads it; it never repeats submit.
    await ctx.call("playwright.page_assert_url",{"url":"**/TreatyManagement/Treaty","role":"cedant"})
    await ctx.call("playwright.page_click",{"selector":"text=全部","role":"cedant"})
    await ctx.call("playwright.page_fill",{"selector":"#查询条件_treatyCode","value":suffix,"role":"cedant"})
    await ctx.call("playwright.page_assert_state",{"selector":{"kind":"role","value":"button","name":"查 询","exact":True},"expected":{"count":1,"enabled":True},"role":"cedant"})
    await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"查 询","exact":True},"role":"cedant"})
    tab={"kind":"role","value":"tab","name":"全部","exact":False}
    await ctx.call("playwright.page_assert_state",{"selector":tab,"expected":{"count":1,"enabled":True},"role":"cedant"})
    await ctx.call("playwright.page_click",{"selector":tab,"role":"cedant"})
    await ctx.call("playwright.page_assert_text",{"selector":"main","text":"平台合约编号："+number,"role":"cedant"})
    links=await ctx.call("playwright.page_list",{"selector":"main a","role":"cedant"})
    if links["truncated"] or len([a for a in links["items"] if a["text"]=="机构合约编号："+suffix])!=1:
        raise ValueError("提交后列表须唯一对应本轮编号")
    after=await states()
    if after[1]["status"]!="3" or after[0]["status"]=="1":
        raise ValueError("再保人尚未进入待确认，或分出方仍待机构审核；保留现场核对")
    return ctx.result(data={"platform_contract_number":number,"contract_suffix":suffix,"participants":after,"after_record_id":watermark_id,"resumed_existing_submission":already_submitted,"cedant_review_levels":0,"decision":"本公司确认并提交至对手方","boundary":"本地专用业务Mock；不证明真实record上链来源"})
