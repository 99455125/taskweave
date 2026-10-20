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
    if inputs["local_mode"]!="business_mock":raise ValueError("本步骤仅验收当前专用业务Mock；真实record来源使用CHAIN任务")
    number=inputs["platform_contract_number"]
    async def query(sql,params,title,max_rows=20):
        r=await ctx.call("tidb.query",{"sql":sql,"params":params,"max_rows":max_rows,"title":title})
        if r["truncated"]:raise ValueError("核对结果被截断："+title)
        return r["rows"]
    observed=[]
    for role,key,account in [("cedant","cedent","000050"),("broker","broker","000053"),("reinsurer","reinsurer","000045")]:
        current=await ctx.call("playwright.page_inspect",{"role":role})
        if not current["url"].startswith("http://localhost:9877/") or current["url"].endswith("/login"):
            await authenticate(role,key,account)
        if current["url"]!="http://localhost:9877/TreatyManagement/Treaty":
            await ctx.call("playwright.page_open",{"url":"http://localhost:9877/TreatyManagement/Treaty","role":role})
        await ctx.call("playwright.page_assert_state",{"selector":"#查询条件_treatyCode","expected":{"count":1,"visible":True},"role":role})
        tab={"kind":"role","value":"tab","name":"全部","exact":False}
        await ctx.call("playwright.page_assert_state",{"selector":tab,"expected":{"count":1,"enabled":True},"role":role})
        await ctx.call("playwright.page_click",{"selector":tab,"role":role})
        await ctx.call("playwright.page_fill",{"selector":"#查询条件_treatyCode","value":number,"role":role})
        button={"kind":"role","value":"button","name":"查 询","exact":True}
        await ctx.call("playwright.page_assert_state",{"selector":button,"expected":{"count":1,"enabled":True},"role":role})
        await ctx.call("playwright.page_click",{"selector":button,"role":role})
        await ctx.call("playwright.page_assert_text",{"selector":"main","text":"平台合约编号："+number,"role":role})
        observed.append({"role":role,"account":account,"platform_contract_number":number})
    master=await query("SELECT id,cedent_treaty_no,org_business_code FROM ri_treaty_master WHERE cedent_treaty_no=%s AND org_business_code=%s AND is_deleted='N'",[number,inputs["contract_suffix"]],"本轮唯一合约")
    if len(master)!=1:raise ValueError("本轮主合约不唯一")
    parties=await query("SELECT id,org_code,reinsurance_role,from_id,status,file_status,org_business_code,amount,broker_rate,biz_id FROM ri_treaty_reinsurer WHERE cedent_treaty_no=%s AND is_deleted='N' ORDER BY id",[number],"三方最终状态")
    if [(r["org_code"],r["reinsurance_role"]) for r in parties]!=[("000050","01"),("000053","03"),("000045","02")]:raise ValueError("三方角色不符")
    if any(r["status"]!="8" for r in parties) or any(r["file_status"]!="2" for r in parties[1:]):raise ValueError("三方业务未全部完成，或两级合同尚未确认")
    if parties[1]["from_id"]!=parties[0]["id"] or parties[2]["from_id"]!=parties[1]["id"]:raise ValueError("上下游关系不符")
    sections=await query("SELECT section_no,section_type,insurance_type_codes,max_limits,commision_rate FROM ri_treaty_proportion WHERE treaty_code=%s AND is_deleted='N' ORDER BY section_no",[number],"两个分项落库")
    if len(sections)!=2:raise ValueError("分项必须恰好2个")
    for i,row in enumerate(sections):
        if set(row["insurance_type_codes"].split(","))!={"04000","01000"} or float(row["max_limits"])!=(i+1)*10000000 or float(row["commision_rate"])!=0.2:
            raise ValueError("分项险种/限额/手续费落库不一致")
    files=await query("SELECT object_id,business_type,attachment_type,attachment_name,attachment_hash FROM ri_business_attachments WHERE object_id IN (%s,%s) AND business_type='01' AND attachment_type='8' AND is_deleted='N' ORDER BY object_id",[parties[1]["id"],parties[2]["id"]],"本轮两个合同附件")
    if len(files)!=2 or [r["object_id"] for r in files]!=[parties[1]["id"],parties[2]["id"]]:raise ValueError("附件归属或数量不符")
    if any(r["attachment_name"]!="tw-local-treaty-demo.pdf" or r["attachment_hash"]!=inputs["expected_attachment_hash"] for r in files):raise ValueError("附件名称或本地Mock文件标识不符")
    details=await query("SELECT id,status,biz_no,onchain_business_id,`from`,`to`,biz_id,onchain_times FROM onchain_job_detail_info WHERE biz_no=%s AND is_deleted='N' ORDER BY id",[number],"本轮上链Mock明细")
    expected_pairs=[("000050","000053",parties[1]["id"]),("000053","000045",parties[2]["id"])]
    if len(details)!=2 or [(r["from"],r["to"],r["onchain_business_id"]) for r in details]!=expected_pairs or any(r["status"]!=8 or not r["biz_id"].startswith("owned-local-treaty-tw-") for r in details):raise ValueError("本轮Mock业务任务未成功或关联不符")
    jobs=await query("SELECT id,status,job_task,biz_no,operation_type FROM onchain_biz_job_info WHERE biz_no=%s AND is_deleted='N' ORDER BY id",[number],"本轮核心业务任务")
    if len(jobs)!=2 or any(r["status"]!=8 for r in jobs):raise ValueError("本轮核心业务任务未全部完成")
    return ctx.result(data={"master":master[0],"participants":parties,"sections":sections,"attachments":files,"core_jobs":jobs,"mock_details":details,"role_views":observed,"local_business_completed":True,"real_record_source_verified":False,"boundary":"业务Mock直接成功，仅证明本地业务/审核/附件/核心任务完成；未验证真实provider、pangu record来源或链节点，使用CHAIN任务另行验收。"})
