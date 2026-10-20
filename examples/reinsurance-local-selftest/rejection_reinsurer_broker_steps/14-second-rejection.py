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
    number=inputs["platform_contract_number"]
    master=await ctx.call("tidb.query",{"sql":"SELECT id,treaty_name,org_business_code FROM ri_treaty_master WHERE id=%s AND cedent_treaty_no=%s AND org_business_code=%s AND is_deleted='N'","params":[inputs["master_id"],number,inputs["contract_suffix"]],"max_rows":2,"title":"第二次退回前冻结本轮本轮主表"})
    if master["truncated"] or master["row_count"]!=1 or master["rows"][0]["treaty_name"]!=inputs["expected_treaty_name"]:raise ValueError("第二次退回前本轮主表或名称变化")
    states=await ctx.call("tidb.query",{"sql":"SELECT id,org_code,from_id,status,reviewer,biz_id FROM ri_treaty_reinsurer WHERE cedent_treaty_no=%s AND is_deleted='N' ORDER BY id","params":[number],"max_rows":4,"title":"第二次退回前本轮三方任务"})
    expected=[(inputs["cedant_id"],"000050",None,"3"),(inputs["broker_id"],"000053",inputs["cedant_id"],"5"),(inputs["source_id"],"000045",inputs["broker_id"],"3")]
    if states["truncated"] or states["row_count"]!=3 or [(r["id"],r["org_code"],r["from_id"],str(r["status"])) for r in states["rows"]]!=expected:raise ValueError("第二次退回前任务阶段或上下游不符，不重复退回")
    if states["rows"][2]["biz_id"]!=inputs["expected_biz_id"] or states["rows"][2]["reviewer"] not in [None,"","000045"]:raise ValueError("退回任务业务或领取归属变化")
    previous=await ctx.call("tidb.query",{"sql":"SELECT id,SHA2(back_up_data,256) AS snapshot_sha256 FROM t_business_back_up_data WHERE source_table=2 AND source_id=%s AND is_deleted='N' ORDER BY id","params":[inputs["source_id"]],"max_rows":2,"title":"二次退回前仍保留V1快照"})
    if previous["truncated"] or previous["row_count"]!=1 or previous["rows"][0]["id"]!=inputs["snapshot_id"] or previous["rows"][0]["snapshot_sha256"]!=inputs["snapshot_sha256"]:raise ValueError("二次退回前旧快照已变化或本轮已经再次退回，停止重提")
    fee=await ctx.call("tidb.query",{"sql":"SELECT broker_rate FROM ri_treaty_reinsurer WHERE id=%s AND from_id=%s AND cedent_treaty_no=%s AND is_deleted='N'","params":[inputs["source_id"],inputs["broker_id"],number],"max_rows":2,"title":"二次退回前实时V2费率"})
    if fee["truncated"] or fee["row_count"]!=1 or abs(float(fee["rows"][0]["broker_rate"])*100-inputs["v2_broker_rate"])>0.000001:raise ValueError("二次退回前实时V2费率不符")
    await authenticate("reinsurer","reinsurer","000045")
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
    await ctx.call("playwright.page_assert_value",{"selector":"#treatyName","value":inputs["contract_suffix"],"role":"reinsurer"})
    name=await ctx.call("playwright.page_input_value",{"selector":"#treatyName","role":"reinsurer"})
    if name["value"]!=inputs["contract_suffix"]:raise ValueError("退回页面不是预期V2")
    await ctx.call("playwright.page_assert_state",{"selector":"input[id$='_brokerRate']","expected":{"count":1,"visible":True,"editable":False},"role":"reinsurer"})
    rate=await ctx.call("playwright.page_input_value",{"selector":"input[id$='_brokerRate']","role":"reinsurer"})
    if abs(float(rate["value"].replace(",",""))-inputs["v2_broker_rate"])>0.000001:raise ValueError("再保待确认页未读取实时V2费率，停止二次退回")
    decision={"kind":"label","value":"退回至经纪人","exact":True}
    await ctx.call("playwright.page_check",{"selector":decision,"checked":True,"role":"reinsurer"})
    await ctx.call("playwright.page_assert_checked",{"selector":decision,"checked":True,"role":"reinsurer"})
    reason="仅供本地自测 "+inputs["contract_suffix"]+" 再保人退回经纪人 V2"
    await ctx.call("playwright.page_fill",{"selector":"#comments","value":reason,"role":"reinsurer"})
    await ctx.call("playwright.page_assert_value",{"selector":"#comments","value":reason,"role":"reinsurer"})
    await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":"reinsurer"})
    await ctx.call("playwright.page_assert_url",{"url":"http://localhost:9877/TreatyManagement/Treaty","role":"reinsurer"})
    after=await ctx.call("tidb.query",{"sql":"SELECT id,org_code,from_id,status,biz_id FROM ri_treaty_reinsurer WHERE cedent_treaty_no=%s AND is_deleted='N' ORDER BY id","params":[number],"max_rows":4,"title":"第二次退回后分出方3经纪13再保4"})
    expected=[(inputs["cedant_id"],"000050",None,"3"),(inputs["broker_id"],"000053",inputs["cedant_id"],"13"),(inputs["source_id"],"000045",inputs["broker_id"],"4")]
    if after["truncated"] or after["row_count"]!=3 or [(r["id"],r["org_code"],r["from_id"],str(r["status"])) for r in after["rows"]]!=expected:raise ValueError("退回后状态不符，保留现场，不重提退回")
    backups=await ctx.call("tidb.query",{"sql":"SELECT id,source_table,source_id,is_deleted,SHA2(back_up_data,256) AS snapshot_sha256,JSON_UNQUOTE(JSON_EXTRACT(back_up_data,'$.riTreatyMasterDTO.treatyName')) AS frozen_name,JSON_UNQUOTE(JSON_EXTRACT(back_up_data,'$.currentTreatyReinsurer.id')) AS frozen_party_id,JSON_UNQUOTE(JSON_EXTRACT(back_up_data,'$.currentTreatyReinsurer.brokerRate')) AS frozen_rate,JSON_UNQUOTE(JSON_EXTRACT(back_up_data,'$.riTreatyMasterDTO.cedentTreatyNo')) AS frozen_number FROM t_business_back_up_data WHERE source_table=2 AND source_id=%s ORDER BY id","params":[inputs["source_id"]],"max_rows":3,"title":"第二次退回替换旧快照并冻结V2"})
    if backups["truncated"] or backups["row_count"]!=2:raise ValueError("二次退回未生成恰好两版快照，先诊断不重提")
    old,new=backups["rows"]
    if old["id"]!=inputs["snapshot_id"] or old["is_deleted"]!="Y" or old["snapshot_sha256"]!=inputs["snapshot_sha256"] or new["id"]<=old["id"] or new["is_deleted"]!="N" or not new["snapshot_sha256"] or new["snapshot_sha256"]==old["snapshot_sha256"] or new["frozen_name"]!=inputs["expected_treaty_name"]:raise ValueError("旧快照逻辑删除或新V2冻结内容不符，不重提退回")
    if any(str(x["frozen_party_id"])!=str(inputs["source_id"]) or x["frozen_number"]!=number for x in [old,new]) or abs(float(old["frozen_rate"])-inputs["v1_broker_rate"])>0.000001 or abs(float(new["frozen_rate"])-inputs["v2_broker_rate"])>0.000001:raise ValueError("二次退回冻结参与方或1%/2.5%版本不符，不重复退回")
    return ctx.result(data={"platform_contract_number":number,"contract_suffix":inputs["contract_suffix"],"source_table":2,"source_id":inputs["source_id"],"snapshots":backups["rows"],"snapshot_id":new["id"],"snapshot_sha256":new["snapshot_sha256"],"frozen_treaty_name":new["frozen_name"],"frozen_broker_rate_percent":float(new["frozen_rate"]),"reason":reason,"participants_after":after["rows"],"second_rejection_performed":True,"boundary":"正常UI第二次退回及本地精确Mock；旧Y新N且唯一有效V2，真实链record未验证"})
