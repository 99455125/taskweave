async def run(ctx, inputs):
    role="cedant"
    master=await ctx.call("tidb.query",{"sql":"SELECT id,record_no,statement_status,comment FROM ri_statement WHERE id=%s AND input_org_code='000050' AND is_deleted='N'","params":[inputs["statement_id"]],"max_rows":2,"title":"本轮账单主表提交防重"})
    if master["truncated"] or master["row_count"]!=1 or master["rows"][0]["comment"]!="仅供本地自测 "+inputs["bill_label"]:raise ValueError("本轮账单主表或备注标识不符")
    if not master["rows"][0]["record_no"].startswith(inputs["platform_treaty_no"]+"-SOAP"):raise ValueError("本轮账单关联合约编号不符")
    master_status=master["rows"][0]["statement_status"]
    if master_status not in [0,3]:raise ValueError("主表不是草稿或已提交待处理，停止重复操作")
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
    resumed=master_status!=0
    recovery=None
    if resumed and not before[0]["biz_id"] and inputs["recover_this_fixture"]:
        if inputs["statement_id"]!=544940 or [r["id"] for r in before]!=[257312,257313]:raise ValueError("精准恢复仅适用当前明确登记的本地夹具")
        recovery=await ctx.call("process.run",{"executable":"/Users/xiaojuju/Projects/company/bjs/dev-environment/imports/verify-venv/bin/python","args":["/Users/xiaojuju/Projects/company/bjs/dev-environment/test-support/retry_owned_bill_precheck.py","--execute","--job-id","1768115023432721898","--detail-id","1768114586986032181"],"timeout_seconds":90,"max_output_bytes":65536})
        if recovery["exit_code"]!=0 or recovery["stdout_truncated"] or recovery["stderr_truncated"]:raise ValueError("精准恢复未明确完成，保留证据，不重复回放或提交")
    if not resumed:
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
    after=await current(False)
    items=await verified_items(after)
    role_states=await ctx.call("tidb.query",{"sql":"SELECT statement_normal_id,reinsurance_role,statement_status,org_code,first_operator FROM ri_statement_normal_state WHERE statement_normal_id IN (%s,%s) AND is_deleted='N' ORDER BY statement_normal_id,org_code","params":[r["id"] for r in after],"max_rows":10,"title":"本轮账单实际角色待确认状态"})
    expected_states=[(after[0]["id"],"000050","01",3),(after[0]["id"],"000053","02",3),(after[1]["id"],"000045","02",0),(after[1]["id"],"000053","01",0)]
    if role_states["truncated"] or [(r["statement_normal_id"],r["org_code"],r["reinsurance_role"],r["statement_status"]) for r in role_states["rows"]]!=expected_states:raise ValueError("实际角色状态尚未到经纪待确认；normal表状态不能代替角色状态")
    if not after[0]["biz_id"] or not after[0]["platform_statement_no"]:raise ValueError("账单尚未进入经纪人待确认，保留当前提交结果继续核对")
    return ctx.result(data={"statement_id":inputs["statement_id"],"platform_treaty_no":inputs["platform_treaty_no"],"bill_label":inputs["bill_label"],"normals":after,"role_states":role_states["rows"],"items":items,"scoped_recovery":recovery,"resumed_existing_submission":resumed,"cedant_review_levels":0,"boundary":"本地业务Mock直接成功，分出方提交到经纪人待确认；不证明pangu record或真实上链。"})
