async def run(ctx, inputs):
    # Existing local credentials stay outside portable task packages and outputs.
    credentials = await ctx.call("file.read", {
        "path": inputs["credentials_path"], "format": "json", "max_bytes": 65536
    })
    ui = credentials["content"]["ui"]
    if ui["url"] != "http://localhost:9877/login":
        raise ValueError("凭据仅允许用于交接指定的本地登录地址")
    role = inputs["role"]
    account = ui["accounts"][inputs["account_key"]]
    if account != inputs["expected_account"] or not ui["sharedPassword"]:
        raise ValueError("交接账号或已有密码不完整")
    await ctx.call("playwright.page_open", {"url": ui["url"], "role": role})
    await ctx.call("playwright.page_assert_state", {
        "selector": "#username", "expected": {"count": 1, "visible": True}, "role": role
    })
    # Explicitly choose Chinese; browser locale alone does not change product language.
    await ctx.call("playwright.page_click", {
        "selector": "#root > div:nth-of-type(1) > div:nth-of-type(3) > div:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(1) > form:nth-of-type(1) > div:nth-of-type(4) > div:nth-of-type(1) > div:nth-of-type(1)", "role": role
    })
    await ctx.call("playwright.page_click", {
        "selector": {"kind": "role", "value": "option", "name": "中文", "exact": True}, "role": role
    })
    placeholder = await ctx.call("playwright.page_attribute", {
        "selector": "#username", "name": "placeholder", "role": role
    })
    if placeholder["value"] != "请输入用户名":
        raise ValueError("登录页未完成中文切换")
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
    handoff=await ctx.call("file.read",{"path":inputs["completed_treaty_path"],"format":"json","max_bytes":65536})
    treaty=handoff["content"]
    if treaty["local_mode"]!="business_mock" or treaty["real_record_source_verified"] is not False:raise ValueError("本轮合约前置的Mock边界不符")
    number=treaty["platform_contract_number"]
    master=await ctx.call("tidb.query",{"sql":"SELECT id,cedent_treaty_no,org_business_code FROM ri_treaty_master WHERE id=%s AND cedent_treaty_no=%s AND is_deleted='N'","params":[treaty["master_id"],number],"max_rows":2,"title":"本轮已完成合约前置"})
    if master["truncated"] or master["row_count"]!=1 or master["rows"][0]["org_business_code"]!=treaty["contract_suffix"]:raise ValueError("本轮合约主键或机构编号不符")
    parties=await ctx.call("tidb.query",{"sql":"SELECT id,org_code,reinsurance_role,from_id,status,file_status FROM ri_treaty_reinsurer WHERE cedent_treaty_no=%s AND is_deleted='N' ORDER BY id","params":[number],"max_rows":10,"title":"本轮三方可出账状态"})
    rows=parties["rows"]
    if parties["truncated"] or [(r["org_code"],r["reinsurance_role"]) for r in rows]!=[("000050","01"),("000053","03"),("000045","02")]:raise ValueError("本轮合约三方不符")
    if any(r["status"]!="8" for r in rows) or any(r["file_status"]!="2" for r in rows[1:]):raise ValueError("本轮合约尚未完成或合同文件尚未确认")
    now=await ctx.call("utility.now",{"timezone":inputs["timestamp_timezone"]})
    label=inputs["name_prefix"]+now["compact"]
    if not label or any(not(c.isalnum() or c=="-") for c in label):raise ValueError("账单标识只允许字母数字和连字符")
    section_numbers=[label+"-S1",label+"-S2"]
    duplicate=await ctx.call("tidb.query",{"sql":"SELECT id,cedent_statement_no FROM ri_statement_normal WHERE cedent_statement_no IN (%s,%s,%s) AND input_org_code='000050' AND is_deleted='N'","params":section_numbers+[label+"-TOTAL"],"max_rows":10,"title":"本轮机构账单编号查重"})
    if duplicate["truncated"] or duplicate["row_count"]!=0:raise ValueError("本轮账单编号已经存在，不再新建")
    await ctx.call("playwright.page_open",{"url":"http://localhost:9877/ContractBill/list","role":role})
    await ctx.call("playwright.page_assert_state",{"selector":{"kind":"role","value":"button","name":"新增合约账单","exact":True},"expected":{"count":1,"enabled":True},"role":role})
    return ctx.result(data={"platform_treaty_no":number,"treaty_master_id":treaty["master_id"],"bill_label":label,"cedent_statement_numbers":section_numbers,"parties":rows,"duplicate_count":0,"timestamp":now,"boundary":"仅证明本轮合约可用、机构账单编号未重复及新增入口可观察；账单列表完整性和新单创建另行验证。"})
