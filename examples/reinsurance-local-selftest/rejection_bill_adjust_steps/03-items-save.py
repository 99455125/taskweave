async def run(ctx, inputs):
    role='cedant'
    async def query(sql,params,title,limit=10):
        r=await ctx.call('tidb.query',{'sql':sql,'params':params,'title':title,'max_rows':limit})
        if r['truncated']:raise ValueError('修正保存核对被截断，停止并核查当前单')
        return r
    master=await query("SELECT id,treaty_id,treaty_statement_type,former_platform_statement_no,statement_status,comment,record_no FROM ri_statement WHERE id=%s AND input_org_code='000050' AND is_deleted='N'",[inputs['statement_id']],'当前修正草稿保存前归属')
    if master['row_count']!=1:raise ValueError('本轮修正草稿不存在或不唯一')
    m=master['rows'][0]
    if (m['id'],m['treaty_id'],m['treaty_statement_type'],m['former_platform_statement_no'],m['statement_status'])!=(544944,325094,'31','000050-2026PT00011-SOA0001',0):raise ValueError('本轮31原单归属或草稿状态不符')
    if m['comment'] not in ['仅供本地自测 TW-LOCAL-BILL-20261016025047',inputs['v1_comment']]:raise ValueError('修正草稿已含其他业务备注，不覆盖')
    normals=await query("SELECT id,input_org_code,enter_org_code,parent_id,former_statement_normal_id,platform_statement_no FROM ri_statement_normal WHERE statement_id=%s AND is_deleted='N' ORDER BY id",[inputs['statement_id']],'保存前本轮31原AB+BC引用')
    rows=normals['rows']
    if normals['row_count']!=2 or [(r['input_org_code'],r['enter_org_code'],str(r['former_statement_normal_id'])) for r in rows]!=[('000050','000053','257312'),('000053','000045','257313')]:raise ValueError('修正草稿AB+BC引用不符')
    if rows[0]['parent_id'] is not None or rows[1]['parent_id']!=rows[0]['id']:raise ValueError('修正草稿父子关系不符')
    await ctx.call('playwright.page_assert_text',{'selector':'body','text':'用户名称000050','role':role})
    await ctx.call('playwright.page_assert_url',{'url':'**/ContractBill/list/adjustBill_add?id='+str(inputs['statement_id'])+'&**','role':role})
    await ctx.call('playwright.page_assert_value',{'selector':'#formerPlatformStatementNo','value':'000050-2026PT00011-SOA0001','role':role})
    await ctx.call('playwright.page_assert_value',{'selector':'#accountPeriod','value':'2026Q4','role':role})
    await ctx.call('playwright.page_fill',{'selector':'#comment','value':inputs['v1_comment'],'role':role})
    await ctx.call('playwright.page_assert_state',{'selector':'#part-4 table','expected':{'count':2},'role':role})
    for index,party,suffix in [(0,10925281,'-AB'),(1,10925282,'-BC')]:
        table={'kind':'css','value':'#part-4 table','nth':index}
        currency="[id='"+str(party)+"_currency']"
        # Current inherited CNY selection must be explicit before amounts are edited.
        await ctx.call('playwright.page_assert_text',{'selector':".ant-select:has("+currency+")",'text':'CNY','role':role})
        for item in inputs['adjustment_items']:
            row={'kind':'role','value':'row','name':item['name'],'exact':False,'within':table}
            amount={'kind':'css','value':"input[id^='itemAmount-']",'within':row}
            await ctx.call('playwright.page_assert_state',{'selector':amount,'expected':{'count':1,'visible':True,'enabled':True,'editable':True},'role':role})
            await ctx.call('playwright.page_fill',{'selector':amount,'value':item['amount'],'role':role})
            await ctx.call('playwright.page_press',{'selector':amount,'key':'Tab','role':role})
            v=await ctx.call('playwright.page_input_value',{'selector':amount,'role':role})
            # This case accepts only fixed integer1000/0; no floating monetary arithmetic.
            if v['value'].replace(',','').split('.')[0]!=item['amount'] or ('.' in v['value'] and v['value'].split('.')[-1].strip('0')):raise ValueError('本次调整额回读不符')
        number="[id='"+str(party)+"_cedentStatementNo']"
        await ctx.call('playwright.page_fill',{'selector':number,'value':inputs['bill_label']+suffix,'role':role})
        await ctx.call('playwright.page_press',{'selector':number,'key':'Tab','role':role})
        await ctx.call('playwright.page_assert_value',{'selector':number,'value':inputs['bill_label']+suffix,'role':role})
    await ctx.call('playwright.page_wait',{'selector':'.ant-notification-notice-success','state':'hidden','role':role})
    await ctx.call('playwright.page_click',{'selector':{'kind':'role','value':'button','name':'保 存','exact':True},'role':role})
    await ctx.call('playwright.page_wait',{'selector':'.ant-notification-notice-success','state':'visible','role':role})
    saved=await query("SELECT id,treaty_id,record_no,treaty_statement_type,former_treaty_statement_type,former_platform_statement_no,statement_status,comment FROM ri_statement WHERE id=%s AND is_deleted='N'",[inputs['statement_id']],'正常保存31主表和业务备注')
    if saved['row_count']!=1 or saved['rows'][0]['statement_status']!=0 or saved['rows'][0]['comment']!=inputs['v1_comment']:raise ValueError('修正保存后的主表/备注不符，核查已有保存不重复创建')
    normals=await query("SELECT id,statement_id,input_org_code,enter_org_code,parent_id,treaty_reinsurer_id,former_statement_normal_id,former_platform_statement_no,platform_statement_no,cedent_statement_no,currency,net_balance,biz_id,parent_biz_id,sign_biz_id,sign_file_id,settlement_id,settlement_status FROM ri_statement_normal WHERE statement_id=%s AND is_deleted='N' ORDER BY id",[inputs['statement_id']],'本轮31正常保存实际重建明细')
    rows=normals['rows']
    if normals['row_count']!=2 or [(r['input_org_code'],r['enter_org_code'],str(r['former_statement_normal_id']),r['currency'],str(r['net_balance'])) for r in rows]!=[('000050','000053','257312','CNY','1000.00'),('000053','000045','257313','CNY','1000.00')]:raise ValueError('31保存后的原单引用或本次调整净额不符，停止核查已有保存')
    if rows[0]['parent_id'] is not None or rows[1]['parent_id']!=rows[0]['id'] or [r['cedent_statement_no'] for r in rows]!=[inputs['bill_label']+'-AB',inputs['bill_label']+'-BC']:raise ValueError('31保存后的树或独立机构编号不符')
    ids=[r['id'] for r in rows]
    items=await query("SELECT object_id,item_code,item_amount,version FROM ri_statement_section_item WHERE object_type=0 AND object_id IN (%s,%s) AND is_deleted='N' ORDER BY object_id,item_code",ids,'31本次调整科目保存值',12)
    expected={x['code']:x['amount']+'.00' for x in inputs['adjustment_items']}
    if items['row_count']!=8 or any({r['item_code']:str(r['item_amount']) for r in items['rows'] if r['object_id']==id}!=expected for id in ids):raise ValueError('31各科目调整贡献额未正确保存')
    states=await query("SELECT statement_normal_id,org_code,reinsurance_role,statement_status,net_balance FROM ri_statement_normal_state WHERE statement_normal_id IN (%s,%s) AND is_deleted='N' ORDER BY statement_normal_id,org_code",ids,'31保存后实际角色草稿和净额',5)
    if states['row_count']!=4 or any(r['statement_status']!=0 or str(r['net_balance'])!='1000.00' for r in states['rows']):raise ValueError('31角色草稿或调整净额不符')
    return ctx.result(data={'statement_id':inputs['statement_id'],'bill_label':inputs['bill_label'],'v1_comment':inputs['v1_comment'],'record_no':saved['rows'][0]['record_no'],'master':saved['rows'][0],'normals':rows,'source_id':ids[0],'states':states['rows'],'items':items['rows'],'new_adjust_saved_by_user':True,'new_adjust_submitted':False,'boundary':'正常中文31编辑器，两段均录入本次保费调整+1000及其余三科目0；实际保存后核对贡献额1000及重建ID，不等同原总额或原总额20%试算。尚未提交/上链/支付。'})
