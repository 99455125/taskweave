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
    async def query(sql,params,title,limit=3):
        r=await ctx.call("tidb.query",{"sql":sql,"params":params,"max_rows":limit,"title":title})
        if r["truncated"]:raise ValueError("本笔账单领取前查询被截断")
        return r
    master=await query("SELECT id,treaty_id,record_no,comment FROM ri_statement WHERE id=%s AND input_org_code='000050' AND is_deleted='N'",[inputs["statement_id"]],"经纪退回新账单主表归属",2)
    if master["row_count"]!=1 or master["rows"][0]["treaty_id"]!=325094 or master["rows"][0]["record_no"]!=inputs["record_no"] or master["rows"][0]["comment"]!=inputs["v1_comment"]:raise ValueError("经纪退回新账单主表归属或V1备注不符")
    tree=await query("SELECT id,statement_id,input_org_code,enter_org_code,parent_id,treaty_reinsurer_id,currency,net_balance,platform_statement_no,cedent_statement_no,biz_id,reviewer,review_level,JSON_UNQUOTE(JSON_EXTRACT(extra_info,'$.comment')) AS business_comment FROM ri_statement_normal WHERE statement_id=%s AND is_deleted='N' ORDER BY id",[inputs["statement_id"]],"本笔首次提交后的活动normal树")
    n=tree["rows"]
    expected=[(inputs["normal_id"],"000050","000053",None,10925281),(inputs["downstream_normal_id"],"000053","000045",inputs["normal_id"],10925282)]
    if tree["row_count"]!=2 or [(x["id"],x["input_org_code"],x["enter_org_code"],x["parent_id"],x["treaty_reinsurer_id"]) for x in n]!=expected:raise ValueError("本笔normal树或活动ID不符")
    if any(x["currency"]!="CNY" or str(x["net_balance"])!="70000.00" for x in n):raise ValueError("本笔金额或币种不符")
    ab=n[0]
    if ab["cedent_statement_no"]!=inputs["bill_label"]+"-TOTAL" or ab["biz_id"]!=inputs["expected_biz_id"] or ab["business_comment"]!=inputs["v1_comment"]:raise ValueError("本笔AB标识、业务ID或实际V1备注不符")
    if not ab["platform_statement_no"] or any(not(c.isalnum() or c=='-') for c in ab["platform_statement_no"]):raise ValueError("本笔AB平台编号缺失或格式异常")
    role_states=await query("SELECT statement_normal_id,org_code,reinsurance_role,statement_status FROM ri_statement_normal_state WHERE statement_normal_id IN (%s,%s) AND is_deleted='N' ORDER BY statement_normal_id,org_code",[inputs["normal_id"],inputs["downstream_normal_id"]],"本笔首次经纪待确认阶段",5)
    expected_states=[(inputs["normal_id"],"000050","01",3),(inputs["normal_id"],"000053","02",3),(inputs["downstream_normal_id"],"000045","02",0),(inputs["downstream_normal_id"],"000053","01",0)]
    if role_states["row_count"]!=4 or [(x["statement_normal_id"],x["org_code"],x["reinsurance_role"],int(x["statement_status"])) for x in role_states["rows"]]!=expected_states:raise ValueError("本笔未处于首次经纪待确认，不领取")
    if ab["reviewer"] not in [None,"","000053"]:raise ValueError("本笔已由其他账号领取")
    if ab["review_level"] is not None:raise ValueError("首次经纪待确认不应已有审核级次")
    snapshots=await query("SELECT id,is_deleted FROM t_business_back_up_data WHERE source_table=3 AND source_id IN (%s,%s) ORDER BY id",[inputs["normal_id"],inputs["downstream_normal_id"]],"首次账单退回前快照防重",2)
    if snapshots["row_count"]:raise ValueError("本笔已存在退回快照，先核对原运行")
    processing_url="http://localhost:9877/ContractBill/list/confirm?id="+str(inputs["statement_id"])+"&treatyCode="+inputs["platform_treaty_no"]+"&statementNormalId="+str(inputs["normal_id"])+"&status=3&treatyReinsurerId=10925281&recordNo="+ab["platform_statement_no"]
    if ab["reviewer"]!="000053":raise ValueError("本笔经纪尚未领取，先完成独立待确认检查")
    if inputs["v1_item_comment"]!=inputs["bill_label"]+"-BROKER-V1":raise ValueError("本笔经纪V1科目说明规则不符")
    items=await query("SELECT id,object_id,item_code,item_amount,item_comment,version FROM ri_statement_section_item WHERE object_type=0 AND object_id IN (%s,%s) AND is_deleted='N' ORDER BY object_id,item_code,id",[inputs["normal_id"],inputs["downstream_normal_id"]],"首次经纪新增前两段原始科目",10)
    expected=[(n,c,a,1) for n in [inputs["normal_id"],inputs["downstream_normal_id"]] for c,a in [("01","100000.00"),("02","20000.00"),("21","10000.00"),("60","0.00")]]
    if items["row_count"]!=8 or [(x["object_id"],x["item_code"],str(x["item_amount"]),x["version"]) for x in items["rows"]]!=expected:raise ValueError("本笔原始科目已变化或已新增，不重复首次确认")
    await ctx.call("playwright.page_assert_text",{"selector":"body","text":"用户名称000053","role":"broker"})
    await ctx.call("playwright.page_assert_text",{"selector":"body","text":"中文","role":"broker"})
    await ctx.call("playwright.page_assert_url",{"url":processing_url,"role":"broker"})
    await ctx.call("playwright.page_assert_value",{"selector":"#cedentTreatyNo","value":inputs["platform_treaty_no"],"role":"broker"})
    await ctx.call("playwright.page_assert_value",{"selector":"input[id$='-10925281-platformStatementNo']","value":ab["platform_statement_no"],"role":"broker"})
    await ctx.call("playwright.page_assert_value",{"selector":"input[id$='-10925282-platformStatementNo']","value":n[1]["platform_statement_no"],"role":"broker"})
    new_subject="input[id^='subject-'][id$='_itemCode']:not([disabled])"
    new_state=await ctx.call("playwright.page_state",{"selector":new_subject,"role":"broker"})
    if new_state["match_count"]==0:
        add={"kind":"role","value":"button","name":"+ 新增科目","exact":True}
        await ctx.call("playwright.page_assert_state",{"selector":add,"expected":{"count":1,"visible":True,"enabled":True},"role":"broker"})
        await ctx.call("playwright.page_click",{"selector":add,"role":"broker"})
    await ctx.call("playwright.page_assert_state",{"selector":new_subject,"expected":{"count":1,"visible":True,"enabled":True},"role":"broker"})
    row="tr:has("+new_subject+")"
    await ctx.call("playwright.page_assert_state",{"selector":row,"expected":{"count":1,"visible":True},"role":"broker"})
    await ctx.call("playwright.page_click",{"selector":new_subject,"role":"broker"})
    options_css=".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option"
    # Read the actual localized enum; require exactly one other-credit choice.
    await ctx.call("playwright.page_wait",{"selector":".ant-select-dropdown:not(.ant-select-dropdown-hidden)","state":"visible","role":"broker"})
    await ctx.call("playwright.page_assert_state",{"selector":new_subject,"expected":{"count":1,"editable":True},"role":"broker"})
    await ctx.call("playwright.page_fill",{"selector":new_subject,"value":"其他","role":"broker"})
    await ctx.call("playwright.page_wait",{"selector":options_css+":has-text('贷')","state":"visible","role":"broker"})
    choices=await ctx.call("playwright.page_list",{"selector":options_css,"role":"broker"})
    if choices["truncated"]:raise ValueError("科目候选观察被截断，不选择")
    candidates=[x["text"].strip() for x in choices["items"] if ("其他" in x["text"] or "其它" in x["text"]) and "贷" in x["text"]]
    if len(candidates)!=1 or "'" in candidates[0]:raise ValueError("本笔实际其他贷方科目不唯一，不选择猜测科目")
    option_name=candidates[0]
    option_selector=options_css+":has-text('"+option_name+"')"
    await ctx.call("playwright.page_assert_state",{"selector":option_selector,"expected":{"count":1,"visible":True,"enabled":True},"role":"broker"})
    await ctx.call("playwright.page_click",{"selector":option_selector,"role":"broker"})
    comment=row+" input[id$='_itemComment']";amount=row+" input[id^='itemAmount-']"
    await ctx.call("playwright.page_assert_state",{"selector":comment,"expected":{"count":1,"visible":True,"editable":True},"role":"broker"})
    await ctx.call("playwright.page_fill",{"selector":comment,"value":inputs["v1_item_comment"],"role":"broker"})
    await ctx.call("playwright.page_press",{"selector":comment,"key":"Tab","role":"broker"})
    await ctx.call("playwright.page_fill",{"selector":amount,"value":"0","role":"broker"})
    await ctx.call("playwright.page_press",{"selector":amount,"key":"Tab","role":"broker"})
    await ctx.call("playwright.page_assert_value",{"selector":comment,"value":inputs["v1_item_comment"],"role":"broker"})
    entered=await ctx.call("playwright.page_input_value",{"selector":amount,"role":"broker"})
    if float(entered["value"].replace(",",""))!=0:raise ValueError("本笔其他科目必须零金额，不改净额")
    tax={"kind":"label","value":"是","exact":True,"within":{"kind":"css","value":"#brokerageVatRateFreeFlag"}}
    await ctx.call("playwright.page_check",{"selector":tax,"checked":True,"role":"broker"})
    decision={"kind":"label","value":"确认并提交审核","exact":True}
    await ctx.call("playwright.page_assert_state",{"selector":decision,"expected":{"count":1,"visible":True,"enabled":True},"role":"broker","timeout_ms":20000})
    await ctx.call("playwright.page_check",{"selector":decision,"checked":True,"role":"broker"})
    await ctx.call("playwright.page_fill",{"selector":"#comments","value":inputs["bill_label"]+" 经纪新增自有其他零金额科目V1 首次提交审核","role":"broker"})
    await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"button","name":"提 交","exact":True},"role":"broker"})
    await ctx.call("playwright.page_assert_url",{"url":"http://localhost:9877/ContractBill/list","role":"broker","timeout_ms":20000})
    after=await query("SELECT statement_normal_id,org_code,reinsurance_role,statement_status FROM ri_statement_normal_state WHERE statement_normal_id IN (%s,%s) AND is_deleted='N' ORDER BY statement_normal_id,org_code",[inputs["normal_id"],inputs["downstream_normal_id"]],"经纪首次提交审核后实际角色阶段",5)
    expected_after=[(inputs["normal_id"],"000050","01",3),(inputs["normal_id"],"000053","02",1),(inputs["downstream_normal_id"],"000045","02",0),(inputs["downstream_normal_id"],"000053","01",0)]
    if after["row_count"]!=4 or [(x["statement_normal_id"],x["org_code"],x["reinsurance_role"],int(x["statement_status"])) for x in after["rows"]]!=expected_after:raise ValueError("本笔首次经纪确认后未读到审核1，不重复提交")
    level=await query("SELECT review_level,reviewer FROM ri_statement_normal WHERE id=%s AND statement_id=%s AND is_deleted='N'",[inputs["normal_id"],inputs["statement_id"]],"本笔经纪首次审核级次",2)
    if level["row_count"]!=1 or level["rows"][0]["review_level"]!=1:raise ValueError("本笔首次审核级次不是1，不重复提交")
    saved=await query("SELECT id,object_id,item_code,item_amount,item_comment,version FROM ri_statement_section_item WHERE object_type=0 AND object_id IN (%s,%s) AND is_deleted='N' ORDER BY object_id,item_code,id",[inputs["normal_id"],inputs["downstream_normal_id"]],"经纪自有version2其他零金额V1实际保存",11)
    custom=[x for x in saved["rows"] if x["version"]==2]
    if saved["row_count"]!=9 or len(custom)!=1:raise ValueError("本笔经纪新增version2科目未唯一落库，不重复确认")
    v=custom[0]
    if v["object_id"]!=inputs["downstream_normal_id"] or v["item_code"]!="98" or str(v["item_amount"])!="0.00" or v["item_comment"]!=inputs["v1_item_comment"]:raise ValueError("本笔version2行归属/科目/零金额/V1说明不符")
    original=[x for x in saved["rows"] if x["version"]==1]
    if original!=items["rows"]:raise ValueError("本笔version1原科目完整基线变化（含ID和说明）")
    balances=await query("SELECT id,net_balance FROM ri_statement_normal WHERE id IN (%s,%s) AND statement_id=%s AND is_deleted='N' ORDER BY id",[inputs["normal_id"],inputs["downstream_normal_id"],inputs["statement_id"]],"新增零科目前后净额不变",3)
    if balances["row_count"]!=2 or any(str(x["net_balance"])!="70000.00" for x in balances["rows"]):raise ValueError("新增零科目意外改变净额")
    return ctx.result(data={"statement_id":inputs["statement_id"],"record_no":inputs["record_no"],"bill_label":inputs["bill_label"],"platform_treaty_no":inputs["platform_treaty_no"],"normal_id":inputs["normal_id"],"downstream_normal_id":inputs["downstream_normal_id"],"source_table":3,"source_id":inputs["downstream_normal_id"],"ab_platform_no":ab["platform_statement_no"],"bc_platform_no":n[1]["platform_statement_no"],"role_states":after["rows"],"audit_level":1,"custom_item":v,"v1_item_comment":inputs["v1_item_comment"],"selected_option":option_name,"first_confirmation_performed":True,"boundary":"正常UI经纪自有version2其他贷方科目金额0/V1说明已持久化，首次确认仅进入一级审核；未完成两级审核、再保待确认或退回"})
