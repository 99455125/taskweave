async def run(ctx, inputs):
    async def authenticate(role,account_key,expected_account):
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
    views=[]
    for role,key,account,task_id in [("cedant","cedent","000050",inputs["from_task_id"]),("broker","broker","000053",inputs["to_task_id"])]:
        await authenticate(role,key,account)
        url="http://localhost:9877/SettlementManagement/BillSettlement/view?taskId="+str(task_id)+"&status=6&settlementNo="+inputs["settlement_no"]
        await ctx.call("playwright.page_open",{"url":url,"role":role})
        await ctx.call("playwright.page_assert_value",{"selector":"#settlementNo","value":inputs["settlement_no"],"role":role})
        await ctx.call("playwright.page_assert_value",{"selector":"#institutionSettlementNo","value":inputs["run_label"],"role":role})
        await ctx.call("playwright.page_assert_state",{"selector":"#institutionSettlementNo","expected":{"count":1,"visible":True,"enabled":False},"role":role})
        await ctx.call("playwright.page_assert_text",{"selector":"#part-1","text":"待结算","role":role})
        amount=await ctx.call("playwright.page_input_value",{"selector":"#totalAmount","role":role})
        if amount["value"].replace(",","")!=inputs["expected_amount"]:raise ValueError("双方最终详情金额不符")
        await ctx.call("playwright.page_click",{"selector":{"kind":"role","value":"link","name":"结算单明细信息","exact":True},"role":role})
        await ctx.call("playwright.page_assert_text",{"selector":"#part-2","text":"000050-2026PT00011-SOA0001","role":role})
        views.append({"role":role,"account":account,"task_id":task_id,"url":url,"readonly":True,"amount":amount["value"]})
    states=await ctx.call("tidb.query",{"sql":"SELECT id,org_code,status,from_id FROM ri_settlement_reinsurer WHERE settlement_no=%s AND is_deleted='N' ORDER BY business_type","params":[inputs["settlement_no"]],"max_rows":3,"title":"双方最终待结算状态"})
    if states["truncated"] or [(r["id"],r["org_code"],str(r["status"])) for r in states["rows"]]!=[(inputs["from_task_id"],"000050","6"),(inputs["to_task_id"],"000053","6")]:raise ValueError("最终双方状态不符")
    jobs=await ctx.call("tidb.query",{"sql":"SELECT b.id AS parent_id,b.group_id,b.job_task,b.status AS parent_status,d.id AS detail_id,d.onchain_business_id,d.status,d.biz_no,d.biz_id,d.tx_id,d.callback_result FROM onchain_biz_job_info b JOIN onchain_job_detail_info d ON d.biz_job_id=b.id AND d.is_deleted='N' WHERE b.group_id IN (%s,%s) AND b.job_task IN ('SETTLEMENT_PROCESS','SETTLEMENT_CONFIRM_PROCESS') AND b.is_deleted='N' ORDER BY d.id","params":[inputs["from_task_id"],inputs["to_task_id"]],"max_rows":3,"title":"结算发起和确认两级Mock任务"})
    if jobs["truncated"] or jobs["row_count"]!=2 or [(r["group_id"],r["job_task"]) for r in jobs["rows"]]!=[(inputs["from_task_id"],"SETTLEMENT_PROCESS"),(inputs["to_task_id"],"SETTLEMENT_CONFIRM_PROCESS")]:raise ValueError("最终Mock任务范围不符")
    if any(r["status"]!=8 or r["parent_status"]!=8 or r["onchain_business_id"]!=inputs["from_task_id"] or r["biz_no"]!=inputs["settlement_no"] or r["biz_id"]!="owned-local-settlement-tw-174791" or r["callback_result"]!='{"code":"0"}' for r in jobs["rows"]):raise ValueError("最终Mock任务回调未完成")
    if jobs["rows"][0]["tx_id"] is not None or not jobs["rows"][1]["tx_id"]:raise ValueError("历史发起tx缺失或修正后确认tx证据不符，不改写历史")
    master=await ctx.call("tidb.query",{"sql":"SELECT id,settlement_no,institution_settlement_no,currency,total_amount,payer_org_code,receiver_org_code,biz_id,tx_id,busi_order_no,cny_exchange_rate,cny_amount FROM ri_settlement WHERE id=%s AND is_deleted='N'","params":[inputs["settlement_id"]],"max_rows":2,"title":"最终结算及本地清分流水边界"})
    if master["truncated"] or master["row_count"]!=1:raise ValueError("最终主表不唯一")
    m=master["rows"][0]
    if m["settlement_no"]!=inputs["settlement_no"] or m["institution_settlement_no"]!=inputs["run_label"] or m["currency"]!="SETTLE-CNY" or str(m["total_amount"])!=inputs["expected_amount"] or (m["payer_org_code"],m["receiver_org_code"])!=("000050","000053") or m["biz_id"]!="owned-local-settlement-tw-174791" or m["tx_id"] is not None or not m["busi_order_no"]:raise ValueError("最终主表或Mock历史边界不符")
    records=await ctx.call("tidb.query",{"sql":"SELECT id,biz_id,msg_name,otc_flag FROM t_ri_gsc_onchain_record WHERE biz_id=%s AND id>%s ORDER BY id","params":["owned-local-settlement-tw-174791",inputs["after_record_id"]],"max_rows":10,"title":"当前直接Mock与真实record边界"})
    if records["truncated"]:raise ValueError("record边界查询截断")
    return ctx.result(data={"settlement_id":inputs["settlement_id"],"settlement_no":inputs["settlement_no"],"role_views":views,"role_states":states["rows"],"core_mock_jobs":jobs["rows"],"master":m,"after_record_id":inputs["after_record_id"],"record_count":records["row_count"],"local_business_endpoint_verified":True,"record_source_verified":False,"payment_completed":False,"exchange_rate_basis":"本地汇率查询403后原代码默认1；不证明真实汇率","boundary":"本地050→053结算待结算6及双角色只读详情。原发起tx为空、确认tx合成、双签与余额合成；真实record、真实签名与资金支付仍未验收。"})
