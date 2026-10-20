"""Task variables for later rule-driven authoring; draft actions do not consume them yet."""

def obj(properties, required=()):
    return {'type':'object','properties':properties,'required':list(required),'additionalProperties':False}

def business_properties(domain):
    text={'type':'string','minLength':1}
    money={'type':'string','pattern':r'^\d+(\.\d{1,2})?$','description':'十进制金额字符串，避免二进制浮点舍入。'}
    common={
        'run_label':{'type':'string','description':'本轮唯一标识，禁止直接复用历史示例编号。'},
        'name_prefix':{'type':'string','default':'TW-LOCAL-','description':'按后续确认的业务规则配置；同轮只生成一次时间戳。'},
        'timestamp_timezone':{'type':'string','default':'Asia/Shanghai'},
        'timestamp_format':{'type':'string','const':'YYYYMMDDHHmmss','default':'YYYYMMDDHHmmss'},
        'rejection_reason':{'type':'string','minLength':1,'description':'含本轮编号、方向和版本的测试退回/审核意见。'},
    }
    if domain=='treaty':
        common['treaty_options']=obj({
            'contract_type':{'enum':['成数合约','溢额合约','混合比例合约'],'default':'成数合约','description':'差异字段与校验须按实际页面续编，不宣称其他类型已跑通。'},
            'business_year':{'type':'integer','minimum':2000,'maximum':2100},
            'start_date':{'type':'string','format':'date'},'end_date':{'type':'string','format':'date'},
            'main_class':{'type':'string','default':'一揽子'},'currency':{'type':'string','default':'CNY'},
            'estimated_premium':money,
            'sections':{'type':'array','minItems':2,'maxItems':2,'items':obj({
                'name':text,'classes':{'type':'array','uniqueItems':True,'minItems':2,'items':{'enum':['家庭财产保险','机动车辆保险']}},
                'limit':money,'commission_percent':{'type':'number','minimum':0,'maximum':100}
            },['name','classes','limit','commission_percent']),
                        'description':'两个分项，每个分项都勾选两个险种。'},
            'participants':{'type':'array','items':obj({'org_code':text,'role':{'enum':['cedant','broker','reinsurer']},'share_percent':{'type':'number','minimum':0,'maximum':100},'leader':{'type':'boolean'},'attachment_path':text},['org_code','role','share_percent','leader'])},
            'broker_chain':{'enum':['direct','cedant_broker_reinsurer'],'default':'cedant_broker_reinsurer','description':'本地000050→000053→000045；不得套用UAT直连70/30。'},
        })
    elif domain=='bill':
        common['bill_options']=obj({'platform_treaty_no':text,'institution_statement_no':text,
            'period_start':{'type':'string','format':'date'},'period_end':{'type':'string','format':'date'},
            'currency':text,'items':{'type':'array','items':obj({'item_code':text,'amount':money},['item_code','amount'])},
            'original_normal_id':{'type':'integer','minimum':1},'remark_v1':text,'remark_v2':text})
    elif domain=='settlement':
        common['settlement_options']=obj({
            'pair':{'enum':['cedant_reinsurer','cedant_broker','broker_reinsurer'],'description':'每笔仅一个FROM/TO对，分别准备可结算账单。'},
            'from_org_code':text,'to_org_code':text,'statement_normal_ids':{'type':'array','minItems':1,'items':{'type':'integer','minimum':1}},
            'currency':text,'amount':money,'due_date':{'type':'string','format':'date'},
            'settlement_type':{'enum':[1,2],'description':'结算类型：1场内、2场外；与资金结算方式amtSettStyle及record.otc_flag分别判断；实际支付另行授权。'},
            'settlement_id':{'type':'integer','minimum':1,'description':'来源5的快照主键，不能填taskId。'},
            'from_task_id':{'type':'integer','minimum':1},'to_task_id':{'type':'integer','minimum':1},'attachment_path':text})
    else:
        return {}
    for value in common.values():
        value['description']=value.get('description','')+' 业务动作目前为草稿；该变量须在续编代码中显式绑定后生效。'
    return common
