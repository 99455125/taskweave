async def run(ctx, inputs):
    role="cedant"
    master=await ctx.call("tidb.query",{"sql":"SELECT id,record_no,statement_status,comment FROM ri_statement WHERE id=%s AND input_org_code='000050' AND is_deleted='N'","params":[inputs["statement_id"]],"max_rows":2,"title":"本轮账单主表提交防重"})
    if master["truncated"] or master["row_count"]!=1 or master["rows"][0]["comment"]!="仅供本地自测 "+inputs["bill_label"]:raise ValueError("本轮账单主表或备注标识不符")
    if not master["rows"][0]["record_no"].startswith(inputs["platform_treaty_no"]+"-SOAP"):raise ValueError("本轮账单关联合约编号不符")
    master_status=master["rows"][0]["statement_status"]
    if master_status!=0:raise ValueError("本笔账单已经提交或离开草稿，先只读核对原运行，禁止重复提交")
    if master["rows"][0]["record_no"]!=inputs["expected_record_no"]:raise ValueError("独立账单案卷号不符")
    async def current(check_draft_ids):
        data=await ctx.call("tidb.query",{"sql":"SELECT id,statement_id,platform_statement_no,statement_status,net_balance,input_org_code,enter_org_code,biz_id,parent_id FROM ri_statement_normal WHERE statement_id=%s AND is_deleted='N' ORDER BY id","params":[inputs["statement_id"]],"max_rows":10,"title":"本轮账单提交状态"})
        rows=data["rows"]
        if data["truncated"] or data["row_count"]!=2 or (check_draft_ids and [r["id"] for r in rows]!=[r["id"] for r in inputs["expected_normals"]]):raise ValueError("总账单明细版本变化，重新核对当前记录，不重复提交")
        if [(r["input_org_code"],r["enter_org_code"]) for r in rows]!=[("000050","000053"),("000053","000045")]:raise ValueError("账单上下游关系不符")
        if any(str(row["net_balance"])!=str(expected["net_balance"]) for row,expected in zip(rows,inputs["expected_normals"])):raise ValueError("本轮提交前后总账单金额变化")
        if rows[0]["parent_id"] is not None or rows[1]["parent_id"]!=rows[0]["id"]:raise ValueError("本轮新旧总账单父子关系不符")
        return rows
    async def verified_items(rows):
        items=await ctx.call("tidb.query",{"sql":"SELECT object_id,item_code,item_amount FROM ri_statement_section_item WHERE object_type=0 AND object_id IN (%s,%s) AND is_deleted='N' ORDER BY object_id,item_code","params":[r["id"] for r in rows],"max_rows":20,"title":"本轮已保存科目和金额"})
        expected=[(r["id"],i["code"],i["amount"]) for r in rows for i in inputs["expected_items"]]
        if items["truncated"] or [(r["object_id"],r["item_code"],str(r["item_amount"])) for r in items["rows"]]!=expected:raise ValueError("已保存科目与本轮预期不符")
        return items["rows"]
    before=await current(master_status==0)
    await verified_items(before)
    resumed=False
    recovery=None
    jobs=await ctx.call("tidb.query",{"sql":"SELECT id,status FROM onchain_biz_job_info WHERE group_id=%s AND biz_no=%s AND job_task='TREATY_BILL_PROCESS' AND is_deleted='N' ORDER BY id","params":[inputs["statement_id"],inputs["expected_record_no"]],"max_rows":2,"title":"本笔账单首次提交避免重复异步任务"})
    if jobs["truncated"] or jobs["row_count"]:raise ValueError("本笔初始任务已存在，不重复提交")
    watermark=await ctx.call("tidb.query",{"sql":"SELECT MAX(id) AS max_id FROM t_ri_gsc_onchain_record","max_rows":1,"title":"本笔账单初始提交前record水位"})
    if watermark["truncated"] or watermark["row_count"]!=1:raise ValueError("本笔账单record水位读取不唯一")
    ctx.log("本笔账单初始提交前record水位="+str(watermark["rows"][0]["max_id"]))
    if not resumed:
        await ctx.call("playwright.page_assert_text",{"selector":"body","text":"用户名称000050","role":role})
        await ctx.call("playwright.page_assert_url",{"url":"**/ContractBill/list/add?**id="+str(inputs["statement_id"])+"&**","role":role})
        await ctx.call("playwright.page_assert_value",{"selector":"#cedentTreatyNo","value":inputs["platform_treaty_no"],"role":role})
        await ctx.call("playwright.page_assert_value",{"selector":"#comment","value":"仅供本地自测 "+inputs["bill_label"],"role":role})
        warning=".ant-modal-content:has-text('将使用[平台账单编号]作为账单编号')"
        pending=await ctx.call("playwright.page_state",{"selector":warning,"role":role})
        if pending["match_count"]==0:
            await ctx.call("playwright.page_assert_url",{"url":"**/ContractBill/list/add?**id="+str(inputs["statement_id"])+"&**","role":role})
            choice={"kind":"label","value":"本公司确认并提交至对手方","exact":True}
            await ctx.call("playwright.page_check",{"selector":choice,"checked":True,"role":role})
            await ctx.call("playwright.page_fill",{"selector":"#comments","value":"仅供本地自测 "+inputs["bill_label"]+" 分出方提交","role":role})
            await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":role})
        await ctx.call("playwright.page_assert_state",{"selector":warning,"expected":{"count":1,"visible":True},"role":role,"timeout_ms":20000})
        await ctx.call("playwright.page_assert_text",{"selector":warning,"text":"[分出人账单编号]未填写，将使用[平台账单编号]作为账单编号，请确认","role":role})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"确 定","exact":True,"within":{"kind":"css","value":warning}},"role":role})
        await ctx.call("playwright.page_assert_url",{"url":"**/ContractBill/list","role":role,"timeout_ms":20000})
    waiting=await ctx.call("process.run",{"executable":"/Users/xiaojuju/Projects/company/bjs/dev-environment/imports/verify-venv/bin/python","args":["/Users/xiaojuju/Projects/company/bjs/dev-environment/test-support/wait_owned_bill_cb_soap0002.py","--phase","initial"],"timeout_seconds":45,"max_output_bytes":65536})
    ctx.log("本笔首次账单上链只读等待="+waiting["stdout"])
    if waiting["exit_code"]!=0 or waiting["stdout_truncated"] or waiting["stderr_truncated"]:raise ValueError("本笔初始任务尚未完成或回调不符；保留原任务，不重复提交或回放")
    after=await current(False)
    items=await verified_items(after)
    role_states=await ctx.call("tidb.query",{"sql":"SELECT statement_normal_id,reinsurance_role,statement_status,org_code,first_operator FROM ri_statement_normal_state WHERE statement_normal_id IN (%s,%s) AND is_deleted='N' ORDER BY statement_normal_id,org_code","params":[r["id"] for r in after],"max_rows":10,"title":"本轮账单实际角色待确认状态"})
    expected_states=[(after[0]["id"],"000050","01",3),(after[0]["id"],"000053","02",3),(after[1]["id"],"000045","02",0),(after[1]["id"],"000053","01",0)]
    if role_states["truncated"] or [(r["statement_normal_id"],r["org_code"],r["reinsurance_role"],r["statement_status"]) for r in role_states["rows"]]!=expected_states:raise ValueError("实际角色状态尚未到经纪待确认；normal表状态不能代替角色状态")
    if not after[0]["biz_id"] or not after[0]["platform_statement_no"]:raise ValueError("账单尚未进入经纪人待确认，保留当前提交结果继续核对")
    core=await ctx.call("tidb.query",{"sql":"SELECT b.id AS parent_id,b.status AS parent_status,d.id AS detail_id,d.status,d.biz_no,d.onchain_business_id,d.biz_id,d.callback_result,d.onchain_times FROM onchain_biz_job_info b JOIN onchain_job_detail_info d ON d.biz_job_id=b.id AND d.is_deleted='N' WHERE b.group_id=%s AND b.biz_no=%s AND b.job_task='TREATY_BILL_PROCESS' AND b.is_deleted='N' ORDER BY b.id,d.id","params":[inputs["statement_id"],inputs["expected_record_no"]],"max_rows":2,"title":"本笔唯一首次账单异步任务及实际回调"})
    if core["truncated"] or core["row_count"]!=1:raise ValueError("本笔初始任务不唯一")
    job=core["rows"][0]
    if job["parent_status"]!=8 or job["status"]!=8 or job["callback_result"] not in ["成功","Success"] or job["onchain_business_id"]!=after[0]["id"] or job["biz_no"]!=after[0]["platform_statement_no"] or job["biz_id"]!=inputs["expected_biz_id"]:raise ValueError("本笔初始账单任务或实际成功回调不符")
    return ctx.result(data={"statement_id":inputs["statement_id"],"platform_treaty_no":inputs["platform_treaty_no"],"bill_label":inputs["bill_label"],"normals":after,"role_states":role_states["rows"],"items":items,"initial_core_mock_job":job,"after_record_id":watermark["rows"][0]["max_id"],"scoped_recovery":recovery,"resumed_existing_submission":resumed,"cedant_review_levels":0,"boundary":"本地业务Mock直接成功，分出方提交到经纪人待确认；不证明pangu record或真实上链。"})
