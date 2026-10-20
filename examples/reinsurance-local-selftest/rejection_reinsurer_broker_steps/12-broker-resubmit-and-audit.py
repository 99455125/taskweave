async def run(ctx, inputs):
    async def authenticate(role, account_key, expected_account):
        # Existing local credentials stay outside portable task packages and outputs.
        credentials = await ctx.call("file.read", {
            "path": inputs["credentials_path"], "format": "json", "max_bytes": 65536
        })
        ui = credentials["content"]["ui"]
        if ui["url"] != "http://localhost:9877/login":
            raise ValueError("凭据仅允许用于交接指定的本地登录地址")
        account = ui["accounts"][account_key]
        if account != expected_account or not ui["sharedPassword"]:
            raise ValueError("交接账号或已有密码不完整")
        current=await ctx.call("playwright.page_inspect",{"role":role})
        if current["url"].startswith("http://localhost:9877/") and not current["url"].endswith("/login"):
            await ctx.call("playwright.page_assert_text",{"selector":"body","text":"用户名称"+account,"role":role})
            await ctx.call("playwright.page_assert_text",{"selector":"body","text":"中文","role":role})
            return
        await ctx.call("playwright.page_open", {"url": ui["url"], "role": role})
        await ctx.call("playwright.page_assert_state", {
            "selector": "#username", "expected": {"count": 1, "visible": True}, "role": role
        })
        placeholder=await ctx.call("playwright.page_attribute",{"selector":"#username","name":"placeholder","role":role})
        if placeholder["value"]!="请输入用户名":
            await ctx.call("playwright.page_click",{"selector":"#root > div:nth-of-type(1) > div:nth-of-type(3) > div:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(1) > form:nth-of-type(1) > div:nth-of-type(4) > div:nth-of-type(1) > div:nth-of-type(1)","role":role})
            option={"kind":"role","value":"option","name":"中文","exact":True}
            await ctx.call("playwright.page_assert_state",{"selector":option,"expected":{"count":1,"visible":True},"role":role})
            await ctx.call("playwright.page_click",{"selector":option,"role":role})
        placeholder=await ctx.call("playwright.page_attribute",{"selector":"#username","name":"placeholder","role":role})
        if placeholder["value"]!="请输入用户名":raise ValueError("登录页尚未切换中文")
        await ctx.call("playwright.page_fill", {"selector": "#username", "value": account, "role": role})
        await ctx.call("playwright.page_fill", {"selector": "#password", "value": ui["sharedPassword"], "role": role})
        # Local handoff explicitly disables image verification; never reuse this for UAT.
        await ctx.call("playwright.page_fill", {"selector": "#verifyCode", "value": str(ui["captcha"]), "role": role})
        await ctx.call("playwright.page_click", {
            "selector": {"kind": "role", "value": "button", "name": "登 录", "exact": True}, "role": role
        })
        await ctx.call("playwright.page_assert_state", {
            "selector": "#emailOrTokenVerifyCode", "expected": {"count": 1, "visible": True}, "role": role
        })
        await ctx.call("playwright.page_fill", {
            "selector": "#emailOrTokenVerifyCode", "value": str(ui["emailCode"]), "role": role
        })
        await ctx.call("playwright.page_click", {
            "selector": {"kind": "role", "value": "button", "name": "确 认", "exact": True}, "role": role
        })
        await ctx.call("playwright.page_assert_url", {"url": "http://localhost:9877/Home", "role": role})
        await ctx.call("playwright.page_assert_text", {"selector": "body", "text": "用户名称" + account, "role": role})
    role="broker"
    async def open_pending():
        current=await ctx.call("playwright.page_inspect",{"role":role})
        if current["url"] in ["http://localhost:9877/TreatyManagement/Treaty/entry", "http://localhost:9877/TreatyManagement/Treaty/audit"]:
            await ctx.call("playwright.page_assert_url",{"url":"**cedentTreatyNo="+inputs["platform_contract_number"]+"&**","role":role})
            return
        current=await ctx.call("playwright.page_inspect",{"role":role})
        if not current["url"].startswith("http://localhost:9877/") or current["url"].endswith("/login"):
            await authenticate("broker","broker","000053")
        if current["url"]!="http://localhost:9877/TreatyManagement/Treaty":
            await ctx.call("playwright.page_open",{"url":"http://localhost:9877/TreatyManagement/Treaty","role":role})
        await ctx.call("playwright.page_assert_state",{"selector":"#查询条件_treatyCode","expected":{"count":1,"visible":True},"role":role})
        await ctx.call("playwright.page_click",{"selector":"text=全部","role":role})
        await ctx.call("playwright.page_fill",{"selector":"#查询条件_treatyCode","value":inputs["platform_contract_number"],"role":role})
        await ctx.call("playwright.page_assert_state",{"selector":{"kind":"role","value":"button","name":"查 询","exact":True},"expected":{"count":1,"enabled":True},"role":role})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"查 询","exact":True},"role":role})
        await ctx.call("playwright.page_assert_text",{"selector":"main","text":"平台合约编号："+inputs["platform_contract_number"],"role":role})
        page_text=await ctx.call("playwright.page_text",{"selector":"main","role":role})
        if page_text["text"].count("平台合约编号："+inputs["platform_contract_number"])!=1:raise ValueError("经纪任务未唯一匹配本轮平台编号")
        tabs=await ctx.call("playwright.page_list",{"selector":{"kind":"role","value":"tab"},"role":role})
        ctx.log("当前任务页签："+str(tabs))
        target={"kind":"role","value":"tab","name":"我的任务","exact":False}
        await ctx.call("playwright.page_assert_state",{"selector":target,"expected":{"count":1,"enabled":True},"role":role})
        await ctx.call("playwright.page_click",{"selector":target,"role":role})
        card='div[class*="list-item_"]:has(a:text-is("平台合约编号：'+inputs["platform_contract_number"]+'"))'
        await ctx.call("playwright.page_assert_state",{"selector":card,"expected":{"count":1,"visible":True},"role":role})
        await ctx.call("playwright.page_assert_text",{"selector":card,"text":"平台合约编号："+inputs["platform_contract_number"],"role":role})
        process={"kind":"role","value":"button","name":"处 理","exact":True,"within":{"kind":"css","value":card}}
        await ctx.call("playwright.page_assert_state",{"selector":process,"expected":{"count":1,"enabled":True},"role":role})
        await ctx.call("playwright.page_click",{"selector":process,"role":role})
    number=inputs["platform_contract_number"]
    async def query(sql,params,title,limit=4):
        r=await ctx.call("tidb.query",{"sql":sql,"params":params,"max_rows":limit,"title":title})
        if r["truncated"]:raise ValueError("本笔重提查询被截断")
        return r
    async def states():
        r=await query("SELECT id,org_code,reinsurance_role,from_id,status,review_level,reviewer,biz_id,broker_rate FROM ri_treaty_reinsurer WHERE cedent_treaty_no=%s AND is_deleted='N' ORDER BY id",[number],"本笔再保退经纪重提前后参与方")
        expected=[(inputs["cedant_id"],"000050","01",None),(inputs["broker_id"],"000053","03",inputs["cedant_id"]),(inputs["source_id"],"000045","02",inputs["broker_id"])]
        if r["row_count"]!=3 or [(x["id"],x["org_code"],x["reinsurance_role"],x["from_id"]) for x in r["rows"]]!=expected:raise ValueError("本笔重提参与方身份或直属关系不符")
        rows=r["rows"]
        if rows[1]["biz_id"]!=inputs["expected_ab_biz_id"] or rows[2]["biz_id"]!=inputs["expected_biz_id"]:raise ValueError("本笔重提AB/BC业务标识不符")
        if rows[2]["broker_rate"] is None or abs(float(rows[2]["broker_rate"])*100-inputs["broker_rate"])>0.000001:raise ValueError("本笔重提实时V2费率不符")
        if rows[1]["reviewer"] not in [None,"","000053"]:raise ValueError("本笔重提已由其他账号领取")
        return rows
    async def snapshot():
        r=await query("SELECT id,SHA2(back_up_data,256) AS snapshot_sha256 FROM t_business_back_up_data WHERE source_table=2 AND source_id=%s AND is_deleted='N' ORDER BY id",[inputs["source_id"]],"重提保留首次V1快照",2)
        if r["row_count"]!=1 or r["rows"][0]["id"]!=inputs["snapshot_id"] or r["rows"][0]["snapshot_sha256"]!=inputs["snapshot_sha256"]:raise ValueError("本笔重提旧快照已变或丢失")
        return r["rows"][0]
    master=await query("SELECT id,treaty_name FROM ri_treaty_master WHERE id=%s AND cedent_treaty_no=%s AND org_business_code=%s AND is_deleted='N'",[inputs["master_id"],number,inputs["contract_suffix"]],"本笔重提主表归属",2)
    if master["row_count"]!=1 or master["rows"][0]["treaty_name"]!=inputs["expected_treaty_name"]:raise ValueError("本笔重提主表归属变化")
    before=await states()
    if [str(x["status"]) for x in before]!=["3","13","4"]:raise ValueError("本笔未处于经纪退回待重提阶段，不重复发送")
    await snapshot()
    jobs=await query("SELECT id,status FROM onchain_biz_job_info WHERE group_id=%s AND biz_no=%s AND job_task='TREATY_PROCESS' AND is_deleted='N' ORDER BY id",[inputs["broker_id"],number],"首次BC基线及重复重提守卫",3)
    if jobs["row_count"]!=1 or jobs["rows"][0]["id"]!=inputs["before_job_id"] or jobs["rows"][0]["status"]!=8:raise ValueError("本笔BC重提任务已存在或首次基线不符，不重复提交")
    await authenticate("broker","broker","000053")
    await open_pending()
    await ctx.call("playwright.page_assert_url",{"url":"**/TreatyManagement/Treaty/cendentrollback?**cedentTreatyNo="+number+"&**id="+str(inputs["broker_id"])+"&**","role":role})
    await ctx.call("playwright.page_assert_value",{"selector":"#treatyName","value":inputs["contract_suffix"],"role":role})
    await ctx.call("playwright.page_assert_value",{"selector":"#orgBusinessCodeEntry","value":"BR-"+inputs["contract_suffix"],"role":role})
    await ctx.call("playwright.page_assert_state",{"selector":"input[id$='_brokerRate']","expected":{"count":1,"visible":True,"editable":True},"role":role})
    rate=await ctx.call("playwright.page_input_value",{"selector":"input[id$='_brokerRate']","role":role})
    if abs(float(rate["value"].replace(",",""))-inputs["broker_rate"])>0.000001:raise ValueError("经纪重提页不是V2费率")
    await ctx.call("playwright.page_check",{"selector":{"kind":"label","value":"确认并提交审核","exact":True},"checked":True,"role":role})
    comment="仅供本地自测 "+inputs["contract_suffix"]+" 经纪V2重提"
    await ctx.call("playwright.page_fill",{"selector":"#comments","value":comment,"role":role})
    await ctx.call("playwright.page_assert_value",{"selector":"#comments","value":comment,"role":role})
    await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":role})
    dialog={"kind":"role","value":"dialog","name":"参与方信息确认","exact":True}
    await ctx.call("playwright.page_assert_state",{"selector":dialog,"expected":{"count":1,"visible":True},"role":role})
    for text in ["000053-","000045-","再保人自行操作"]:
        await ctx.call("playwright.page_assert_text",{"selector":dialog,"text":text,"role":role})
    await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"确 定","exact":True,"within":dialog},"role":role})
    await ctx.call("playwright.page_assert_url",{"url":"**/TreatyManagement/Treaty","role":role})
    audit_levels=[]
    record_watermark=None
    for level in ["1","2"]:
        rows=await states()
        if rows[1]["status"]=="5" and rows[2]["status"]=="3":break
        if rows[1]["status"]!="1":raise ValueError("经纪确认尚未进入机构审核；先核对本次提交，不重复")
        if str(rows[1]["review_level"])!=level:
            if level=="1" and str(rows[1]["review_level"])=="2":continue
            raise ValueError("机构审核级次不符合本地双级配置")
        await open_pending()
        await ctx.call("playwright.page_assert_url",{"url":"**/TreatyManagement/Treaty/audit?**","role":role})
        if level=="2":
            watermark=await ctx.call("tidb.query",{"sql":"SELECT MAX(id) AS max_id FROM t_ri_gsc_onchain_record","max_rows":1,"title":"V2 BC重提终审前record水位"})
            if watermark["truncated"] or watermark["row_count"]!=1:raise ValueError("V2 BC重提终审前水位读取异常")
            record_watermark=watermark["rows"][0]["max_id"]
            ctx.log("V2 BC重提终审前record水位="+str(record_watermark))
        expected_decision="确认并提交审核" if level=="1" else "本公司确认并提交至再保人"
        await ctx.call("playwright.page_assert_state",{"selector":{"kind":"label","value":expected_decision,"exact":True},"expected":{"count":1,"enabled":True},"role":role})
        page_snapshot=await ctx.call("playwright.page_inspect",{"scope":"full_page","role":role})
        allowed=["确认并提交审核","本公司确认并提交至再保人","本公司确认并提交至对手方"]
        positive=[e for e in page_snapshot["elements"] if e.get("type")=="radio" and e.get("enabled") and e.get("name") in allowed]
        if len(positive)!=1:raise ValueError("当前审核正向决策不唯一，须核对实际页面")
        await ctx.call("playwright.page_check",{"selector":positive[0]["preferred_selector"],"checked":True,"role":role})
        await ctx.call("playwright.page_fill",{"selector":"#comments","value":"仅供本地自测 "+inputs["contract_suffix"]+" 经纪审核"+level,"role":role})
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":role})
        await ctx.call("playwright.page_assert_url",{"url":"**/TreatyManagement/Treaty","role":role})
        audit_levels.append(level)
    waiting=await ctx.call("process.run",{"executable":"/Users/xiaojuju/Projects/company/bjs/dev-environment/imports/verify-venv/bin/python","args":["/Users/xiaojuju/Projects/company/bjs/dev-environment/test-support/wait_owned_br_00014.py","--phase","resubmit-bc","--before-job",str(inputs["before_job_id"]),"--attempt","2"],"timeout_seconds":45,"max_output_bytes":65536})
    ctx.log("本笔V2新BC只读等待="+waiting["stdout"])
    if waiting["exit_code"]!=0 or waiting["stdout_truncated"] or waiting["stderr_truncated"]:raise ValueError("新BC重提尚未唯一成功；保留原任务，不重新提交")
    after=await states()
    if [str(x["status"]) for x in after]!=["3","5","3"]:raise ValueError("经纪双级审核后本笔仍未回到再保待确认")
    unchanged=await snapshot()
    new=await query("SELECT b.id AS parent_id,b.status AS parent_status,d.id AS detail_id,d.status,d.biz_id,d.callback_result,d.onchain_times FROM onchain_biz_job_info b JOIN onchain_job_detail_info d ON d.biz_job_id=b.id AND d.is_deleted='N' WHERE b.group_id=%s AND b.biz_no=%s AND b.job_task='TREATY_PROCESS' AND b.id>%s AND b.is_deleted='N' ORDER BY b.id,d.id",[inputs["broker_id"],number,inputs["before_job_id"]],"本次新BC父和明细核对",2)
    if new["row_count"]!=1 or new["rows"][0]["parent_status"]!=8 or new["rows"][0]["status"]!=8 or new["rows"][0]["biz_id"]!=inputs["expected_biz_id"] or new["rows"][0]["callback_result"]!='{"code":"0"}':raise ValueError("本笔新BC任务或回调不唯一成功")
    return ctx.result(data={"platform_contract_number":number,"contract_suffix":inputs["contract_suffix"],"source_table":2,"source_id":inputs["source_id"],"snapshot":unchanged,"participants":after,"before_job_id":inputs["before_job_id"],"new_core_mock_job":new["rows"][0],"audit_levels_in_this_attempt":audit_levels,"after_record_id":record_watermark,"broker_rate_percent":inputs["broker_rate"],"resubmitted":True,"boundary":"本笔正常经纪重提及两级审核，精确本地Mock；真实record另验收"})
