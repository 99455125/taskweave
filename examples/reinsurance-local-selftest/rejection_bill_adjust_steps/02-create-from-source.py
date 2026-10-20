async def run(ctx, inputs):
    role='cedant'
    async def query(sql,params,title,limit=4):
        r=await ctx.call('tidb.query',{'sql':sql,'params':params,'title':title,'max_rows':limit})
        if r['truncated']:raise ValueError('修正创建核对被截断，停止后按原run核查，不重建')
        return r
    source=await query("SELECT id,statement_id,input_org_code,enter_org_code,parent_id,platform_statement_no,sign_file_id FROM ri_statement_normal WHERE id=%s AND statement_id=%s AND is_deleted='N'",[inputs['source_normal_id'],inputs['source_statement_id']],'修正点击前原AB归属')
    if source['row_count']!=1:raise ValueError('原AB不存在或不唯一')
    n=source['rows'][0]
    if (n['input_org_code'],n['enter_org_code'],n['parent_id'],n['platform_statement_no'])!=('000050','000053',None,inputs['source_platform_no']) or not n['sign_file_id']:raise ValueError('原AB关系/文件不符')
    existing=await query("SELECT id,record_no,statement_status FROM ri_statement WHERE former_platform_statement_no=%s AND is_deleted='N' ORDER BY id",[inputs['source_platform_no']],'源AB已有修正防重复')
    recover=inputs.get('verify_only',False)
    if recover:
        if existing['row_count']!=1 or existing['rows'][0]['id']!=inputs.get('expected_created_draft_id') or inputs.get('expected_created_draft_id')!=544944:raise ValueError('只读恢复必须匹配原创建run确认的544944，不新建')
    elif existing['row_count']:raise ValueError('已有修正单，须按原创建run核查，不再点击修正')
    states=await query("SELECT org_code,reinsurance_role,statement_status FROM ri_statement_normal_state WHERE statement_normal_id=%s AND is_deleted='N' ORDER BY org_code",[inputs['source_normal_id']],'原AB完成角色再确认')
    if [(r['org_code'],r['reinsurance_role'],r['statement_status']) for r in states['rows']]!=[('000050','01',8),('000053','02',8)]:raise ValueError('原AB角色已变化，不创建')
    await ctx.call('playwright.page_assert_text',{'selector':'body','text':'用户名称000050','role':role})
    await ctx.call('playwright.page_assert_text',{'selector':'body','text':'中文','role':role})
    if not recover:
        await ctx.call('playwright.page_assert_url',{'url':'http://localhost:9877/ContractBill/list','role':role})
        row={'kind':'role','value':'row','name':inputs['source_platform_no'],'exact':False,'within':{'kind':'css','value':'.bill-list-box'}}
        adjust={'kind':'role','value':'button','name':'修正','exact':True,'within':row}
        await ctx.call('playwright.page_assert_state',{'selector':adjust,'expected':{'count':1,'visible':True,'enabled':True},'role':role})
        # Exactly one normal UI creation. Any later error requires checking this run and the new draft.
        await ctx.call('playwright.page_click',{'selector':adjust,'role':role})
        await ctx.call('playwright.page_assert_url',{'url':'http://localhost:9877/ContractBill/list/adjustBill_add?**','role':role})
    created=await query("SELECT id,treaty_id,record_no,treaty_statement_type,former_treaty_statement_type,former_platform_statement_no,statement_status,comment FROM ri_statement WHERE former_platform_statement_no=%s AND input_org_code='000050' AND is_deleted='N' ORDER BY id",[inputs['source_platform_no']],'本次正常修正创建31主表')
    if created['row_count']!=1:raise ValueError('修正创建后新主表不唯一；核对原run，不重复点击')
    master=created['rows'][0]
    if (master['treaty_id'],master['treaty_statement_type'],master['former_treaty_statement_type'],master['statement_status'])!=(325094,'31','01',0):raise ValueError('新修正主表类型/原类型/草稿阶段不符')
    normals=await query("SELECT id,statement_id,input_org_code,enter_org_code,parent_id,treaty_reinsurer_id,former_statement_normal_id,former_platform_statement_no,platform_statement_no,currency,net_balance,biz_id,parent_biz_id,sign_biz_id,sign_file_id,settlement_id,settlement_status FROM ri_statement_normal WHERE statement_id=%s AND is_deleted='N' ORDER BY id",[master['id']],'新31实际AB及BC复制树')
    rows=normals['rows']
    if normals['row_count']!=2:raise ValueError('新31未得到AB+BC两段，保留草稿核查')
    a,b=rows
    if [(r['input_org_code'],r['enter_org_code'],r['treaty_reinsurer_id'],str(r['former_statement_normal_id']),r['former_platform_statement_no']) for r in rows]!=[('000050','000053',10925281,'257312',inputs['source_platform_no']),('000053','000045',10925282,'257313','000050-2026PT00011-SOA0002')]:raise ValueError('新31原AB/BC引用不符')
    if a['parent_id'] is not None or b['parent_id']!=a['id']:raise ValueError('新31父子树不符')
    if any(r[k] for r in rows for k in ['biz_id','parent_biz_id','sign_biz_id','sign_file_id','settlement_id','settlement_status']):raise ValueError('新31签章/业务/结算引用没有清空')
    page=await ctx.call('playwright.page_inspect',{'role':role})
    await ctx.call('playwright.page_assert_url',{'url':'**/ContractBill/list/adjustBill_add?id='+str(master['id'])+'&**','role':role})
    return ctx.result(data={'statement_id':master['id'],'record_no':master['record_no'],'bill_label':inputs['bill_label'],'source_statement_id':inputs['source_statement_id'],'source_normal_id':inputs['source_normal_id'],'source_platform_no':inputs['source_platform_no'],'master':master,'normals':rows,'source_id':a['id'],'new_adjust_created':not recover,'existing_created_draft_verified':recover,'creation_run':'6d1e0bd4-4b33-4c10-b50d-31ecdd7d2560' if recover else None,'new_adjust_saved_by_user':False,'new_adjust_submitted':False,'observed_url':page['url'],'boundary':('本次只读复核原创建run的544944，无创建点击；' if recover else '本次正常中文源行修正按钮仅点击一次；')+'核验31及AB+BC复制；克隆金额尚未录入/重算，后续实际编辑保存后才断言净额。未提交/上链/支付；原关系保持。'})
