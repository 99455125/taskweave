"""Build local self-test authoring artifacts from recorded BJS business evidence.

This writes TaskWeave plans and DRAFT tasks through its public application API.
Historical evidence is explicitly labelled; business actions awaiting live capture
remain empty drafts instead of reporting a simulated action as a passed test.
"""
import base64
from datetime import datetime
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BJS = Path('/Users/xiaojuju/Projects/company/bjs')
EVIDENCE = BJS / 'openspec/changes/backupdata-validation-and-record-source/evidence'
OUTPUT = Path('/Users/xiaojuju/taskweave/local-selftest-20261016')


def action(name, role, instructions, expected, sources=()):
    return dict(name=name, role=role, instructions=instructions, expected=expected,
                sources=list(sources), kind='business_draft')


def snapshot(name, sources=(), compare=False):
    return dict(name=name, role='database', kind='snapshot_compare' if compare else 'snapshot',
                instructions='只读核对指定来源的备份表，不修改快照或业务状态。',
                expected='仅1条有效快照；明确记录source_table/source_id、快照ID和SHA256。' + (' 内容与前序快照一致。' if compare else ''),
                sources=list(sources))


def reject_steps(direction, source, source_table):
    sender, receiver = {'direct': ('cedant', 'reinsurer'), 'cb': ('cedant', 'broker'), 'br': ('broker', 'reinsurer')}[direction]
    steps = [
        action('核对本轮待确认任务与领取归属', receiver,
               '使用本轮新建或明确标记的独立夹具，核对业务编号、上下游组织、任务ID和当前状态。领取及双级审核沿用实际权限；合成前置单列。',
               '任务属于当前接收机构，可以确认或退回；保留首次页面及状态。', source),
        action('第一次退回并记录原版本', receiver,
               '选择当前页面明确提供的退回方向，填写唯一的本地自测原因并提交。',
               '退回成功；核对发送方待修改、接收方退回状态，不能仅按提交按钮无报错判断。', source),
        snapshot('读取第一次退回快照', source),
        action('发送方修改第二版并暂存', sender,
               '合约修改名称/经纪费率，账单修改备注；修改前记录V1，修改后回读V2，只保存暂存。',
               '实时数据已是V2，接收方退回详情仍为只读V1。', source),
        snapshot('核对暂存后旧快照未变', source, compare=True),
        action('重提并完成实际机构审核', sender,
               '重新提交；按实际机构审核级次完成审核。记录真实待确认状态和领取人；Mock回调或领取夹具另行标记。',
               '接收方重新获得待确认任务，前次有效快照仍保留，重提不会清空快照。', source),
        snapshot('核对重提后旧快照仍保留', source, compare=True),
        action('第二次退回并核对版本替换', receiver,
               '接收方再退回；读取V2快照，核对前次快照逻辑删除、有效快照仅1条，详情为只读V2。',
               f'来源{source_table}的目标ID正确；旧快照Y、新快照N；不同来源同ID互不污染。', source),
        snapshot('读取第二次退回后的有效快照', source),
    ]
    if len(source) >= 4:
        for step,index in zip(steps,[0,0,0,1,1,2,2,3,3]):
            step['sources']=[source[index]]
    return steps


def cases():
    items = []
    def add(key, domain, title, steps, **extra):
        items.append(dict(key=key, domain=domain, title=title, steps=steps, **extra))
    add('ENV-01', 'environment', '本地环境与角色登录核对', [
        dict(name='检查本地目录与依赖程序', role='local', kind='environment', sources=[], instructions='核对BJS根目录、证据目录和Python路径。', expected='路径可用；只读检查不启动或停止BJS服务。'),
        dict(name='连接本地TiDB并核对库名', role='database', kind='database', sources=[], instructions='连接交接指定本地数据库。', expected='连接成功且数据库为本地交接库。'),
        action('分出方登录并核对身份', 'cedant', '使用本机受限配置提供的账号、密码通过正常前端认证登录。显式中文界面。', '当前机构为000050，账户身份和组织一致。'),
        action('经纪人登录并核对身份', 'broker', '使用独立浏览器role；核对本地合成经纪链路中的000053及实际权限。', '000053本地经纪测试角色可用；不把机构名称当作生产经纪资格依据。'),
        action('再保人登录并核对身份', 'reinsurer', '使用独立浏览器role；核对000045和实际可处理任务。', '当前机构000045；与其他角色的登录状态隔离。'),
    ])
    treaty_sources = ['ui-treaty-fixture.json', 'otc-e2e-internal-treaty.json']
    add('TREATY-01', 'treaty', '分出方录入合约 经纪人确认 再保人确认', [
        action('创建本轮唯一编号与查重', 'cedant', '沿用已确认的前缀+北京时间秒级时间戳；查询全部合约确认没有同编号。', '本轮编号仅生成一次且查询0条。', treaty_sources),
        action('新增财产比例合约及基本信息', 'cedant', '显式中文，选择财产保险/比例再保险/成数合约，输入年度、责任期间、主险类、保费、账单周期等变量。', '关键值回读一致；已确认的业务规则存为变量。', treaty_sources),
        action('配置经纪上下游及附件', 'cedant', '按本地三方链配置000050→000053→000045，填写本次份额、是否首席及附件；避免沿用UAT的两家直连70/30关系。', '上下游from_id和角色01/03/02正确；附件存在真实下载链接。', ['ui-broker-treaty-cb-first-rejection.json']),
        action('新增明细分项并保存', 'cedant', '建立两个分项，每个分项都同时勾选家庭财产保险和机动车辆保险；限额/手续费按本轮变量填写并保存。', '两个分项均含这两个险种，逐项独立回读；取得本次平台编号。', treaty_sources),
        action('提交并完成分出方机构审核', 'cedant', '填写本地自测意见，提交并按现有机构审核配置处理。', '记录实际审核级次和任务状态；不把已提交当作已上链完成。', treaty_sources),
        action('经纪人确认和机构审核', 'broker', '按平台编号找到本笔任务，领取、核对上游和下游、补录经纪字段，按机构审核级次提交。', '经纪人数据及审核记录正确；再保人得到对应任务。', ['ui-broker-treaty-br-resubmit.json']),
        action('再保人确认和机构审核', 'reinsurer', '核对同一合约和份额、费用、附件，确认并完成本机构审核。', '确认状态及业务状态依据实际流转核对；未收到回调前不记完成。', treaty_sources),
        action('经纪人二次确认并提交机构审核', 'broker', '按共享平台编号打开状态6的二次确认任务，核对下游已完成、两个合同文件均存在，选择同意决策提交。分出方不代做合同文件确认。', '本地000053状态6变9、review_level为1；只推进本轮独立合约。', ['ui-broker-treaty-br-resubmit.json']),
        action('经纪人二次确认一级审核', 'broker', '使用当前机构一级审核权限，从我的任务打开本轮合约，核对实际正向决策和意见后提交。', '状态仍9，review_level由1变2；保留真实审核记录。', ['ui-broker-treaty-br-resubmit.json']),
        action('经纪人二次确认二级审核', 'broker', '使用当前机构二级审核权限，核对本轮合约及待审级次，选择正向决策提交。', '经纪人8/file_status2，分出方归集8，再保人保持8/2；若为7则单列缺附件/接收方合同确认，不能强制改状态。', ['ui-broker-treaty-br-resubmit.json']),
        action('核对上链任务和最终业务状态', 'database', '三角色按共享平台编号查看本轮合约；核对三方完成、两合同附件、双险种分项及核心任务。business_mock模式只验收精确白名单Mock；真实provider/pangu/service及record来源在CHAIN任务另行运行。', '三方状态8、经纪及再保文件状态2、两个分项均含双险种且限额/费率正确；核心Mock任务8。明确real_record_source_verified=false，不把Mock当普通场内otc_flag=0通过。', ['otc-e2e-internal-treaty.json']),
    ], dependencies=['ENV-01'])
    for key, direction, title, files in [
        ('TREATY-02','direct','合约 再保人退回分出方 两轮快照隔离',['ui-treaty-first-rejection.json','ui-treaty-draft-isolation.json','ui-treaty-resubmit.json','ui-treaty-second-rejection.json']),
        ('TREATY-03','cb','合约 经纪人退回分出方 两轮快照隔离',['ui-broker-treaty-cb-first-rejection.json','ui-broker-treaty-cb-draft-isolation.json','ui-broker-treaty-cb-resubmit.json','ui-broker-treaty-cb-second-rejection.json']),
        ('TREATY-04','br','合约 再保人退回经纪人 双级审核与快照',['ui-broker-treaty-br-first-rejection.json','ui-broker-treaty-br-draft-isolation.json','ui-broker-treaty-br-resubmit.json','ui-broker-treaty-br-second-rejection.json'])]:
        preparation=[dict(s) for s in items[1]['steps'][:6 if key=='TREATY-04' else 5]]
        if key=='TREATY-02':
            preparation[2]=action('配置直连再保人及附件','cedant','独立050→045直连结构，份额100%、不设首席，上传获准测试PDF。','仅两个参与方且045直属050，不存在053经纪节点。',treaty_sources)
        add(key,'treaty',title,preparation+reject_steps(direction,files,2),snapshot_source_table=2,dependencies=['ENV-01'] if preparation else ['TREATY-01'])
    bill_sources=['ui-bill-fixture.json','otc-e2e-internal-bill.json']
    add('BILL-01','bill','分出方录入合约账单 经纪人确认 再保人确认',[
        action('核对已完成合约与本轮账单编号','cedant','选择本轮实际可用的完成合约；核对是否经过经纪以及两个层级的相关方。','依赖合约满足账单录入条件；业务编号唯一。',bill_sources),
        action('新增总账单并填写期间和项目','cedant','从合约账单新增入口选择合约，填写机构账单编号、期间、币种、保费/赔款/手续费等实际账单项。','总账单、分账单、双方状态和明细ID分别记录。',bill_sources),
        action('试算和保存账单','cedant','执行试算，核对分项和净额、舍入、币种及账单期间后保存。','金额与项目回读一致；不把试算当作已提交。',bill_sources),
        action('提交账单并完成机构审核','cedant','提交并按现有机构审核级次处理，记录回调前后的状态。','接收方待确认；完成合约的合成前置和回调Mock单独标记。',bill_sources),
        action('经纪人核对上游账单并确认','broker','对三方合约定位上游账单，核对明细、经纪费率及下游账单；按现有审核流程确认。','上下游normal_id、parent_id及机构均正确；直连场景在独立任务省略本动作。',['ui-broker-bill-fixtures.json']),
        action('再保人确认合约账单','reinsurer','定位本机构目标分账单，核对金额、明细、期间和机构编号，确认及审核。','本笔账单达到实际约定状态，记录上链/回调证据。',bill_sources),
        action('经纪二次确认并提交审核','broker','再保确认后按本轮上游normal领取经纪二次确认任务，核对金额和父子关系；选择实际页面同意决策提交审核。','经纪上游进入二次审核一级，下游再保保持已完成。',bill_sources),
        action('经纪二次确认一级审核','broker','正常领取二次审核一级任务，选择实际提交审核决策，填写本轮唯一审核说明。','进入二次审核二级，不重复前序确认。',bill_sources),
        action('经纪二次确认二级审核','broker','正常领取二次审核二级任务，核对当前上下游账单后按实际页面决策完成。','上下游全部实际角色达到已完成；业务Mock与真实record来源分列。',bill_sources),
        action('核对本地Mock账单完成与三方详情','database','正常登录三个角色查看本笔详情；只读回读主表、角色状态、金额科目和两段核心Mock回调。','本地Mock业务完成；真实record与列表完整性未验收时明确分列，不抵作下一步通过。',bill_sources),
        action('核对账单上链和列表详情','database','用同笔biz_id核对真实record；列表TiFlash报错需记录本地环境限制，不能以改SQL或伪造列表绕过。','普通场内账单record.otc_flag=0；页面与库内ID关联。',bill_sources),
    ],dependencies=['TREATY-01'])
    for key,direction,title,files in [
        ('BILL-02','direct','合约账单 再保人退回分出方 两轮快照',['ui-bill-first-rejection.json','ui-bill-draft-isolation.json','ui-bill-resubmit.json','ui-bill-second-rejection.json']),
        ('BILL-03','cb','合约账单 经纪人退回分出方 两轮快照',['ui-broker-bill-fixtures.json']),
        ('BILL-04','br','合约账单 再保人退回经纪人 两轮快照',['ui-broker-bill-fixtures.json'])]:
        preparation=[dict(s) for s in next(c for c in items if c['key']=='BILL-01')['steps'][:4]] if key in {'BILL-02','BILL-03','BILL-04'} else []
        if key=='BILL-02':
            preparation[0]['instructions']='核对owner已拥有直连测试基础合约317093/SELFTESTBILL001，明确合成完成/无附件/from_org残留边界；本轮只出新账单，不重放合约。'
            preparation[2]['instructions']='正常UI明确CNY，按实际20%份额试算，总净额70000对应唯一根normal14000，核对050至045无053。'
        if key=='BILL-04':
            preparation += [
                action('经纪首次待确认页与科目可编辑性核对','broker','正常鉴权领取本笔AB待确认3，核对中文身份/金额/上下游并观察实际科目字段；仅领取和观察。','首次3/3/0/0，无两段退回快照；保存页面，不计新增科目/保存/确认/审核已完成。',files),
                action('经纪首次确认并提交审核','broker','正常领取本笔AB待确认3，在正常UI新增本笔经纪自有version2其他科目（98/99），金额0、说明V1，实际试算并确认提交机构审核。','AB经纪进入审核1/level1，BC再保尚未待确认。',files),
                action('经纪首次确认一级审核','broker','正常领取本笔AB审核1/level1，确认并提交下级审核。','AB经纪进入审核1/level2，不重复首次确认。',files),
                action('经纪首次确认二级审核并核对下游待确认','broker','正常领取本笔AB审核1/level2，本公司确认并提交至再保人。','AB050=3/053=5、BC053=3/045=3，核对本笔独立Mock任务及实际活动ID。',files),
            ]
        returns=reject_steps(direction,files,3)
        if key=='BILL-04':
            returns[3]['instructions']='经纪正常退回处理页只修改此前本笔经纪自有version2其他零金额科目的说明为V2并暂存，实际确认该行可编辑；保持金额0。saveBrokerChangeInfo不保存通用comment，通用UI也未保证经纪账单号可编辑。先回读实时V2，再验证045只读旧V1及旧快照完整哈希不变。'
            returns[1]['expected']='AB050/053为3/13、BC053/045为4/4，来源3主键为BC normal；冻结本轮V1。'
        add(key,'bill',title,preparation+returns,snapshot_source_table=3,dependencies=['ENV-01'] if key=='BILL-02' else ['TREATY-01'] if preparation else ['BILL-01'])
    adjust_returns=reject_steps('cb',['ui-treaty-adj-first-rejection.json','ui-treaty-adj-draft-isolation.json','ui-treaty-adj-resubmit.json','ui-treaty-adj-second-rejection.json'],3)
    adjust_returns[0]['instructions']='核对新31账单AB050→053及其BC子段，正常053领取新AB；原normal257312/13及结算174791保持。记录新normal主键，来源3绑定新AB。'
    adjust_returns[1]['expected']='新AB发送方13/接收方4；记录BC实际状态，31跳过普通账单子段先退限制；原账单仍8/8。'
    adjust_returns[3]['instructions']='050正常退回修改页将新31账单的本轮备注从V1改为V2并暂存；不修改原账单，不改业务状态。核对实时V2、053退回只读V1及旧快照SHA。'
    adjust_returns[5]['instructions']='050正常重发31：实际同步chainedTransaction/ADJUST_BILL，核对响应和新AB角色待确认及V2；按实际审核配置执行。31不套普通账单重发方法，也不要求新普通经纪异步父任务。'
    add('BILL-05','bill','合约修正账单 录入确认与退回版本隔离',[
        action('选择可修正的完成账单','cedant','只读核对原544940/AB257312实际角色8/8、已生成文件且无历史修正；正常中文全部列表过滤源平台账单并观察修正按钮。','源关系050→053及结算边界保留，列表真实显示源行且修正可用；本步骤尚不创建。',['ui-broker-bill-fixtures.json']),
        action('通过原账单修正按钮创建31草稿','cedant','再次核对原AB角色8/8且无已有修正后，在真实源行点击修正一次；读取新31与两段复制关系。','新31主表及AB+BC树和原normal引用正确；业务/签章/结算链接清空，不提交。后续失败按原创建run核查，不重复创建。',['ui-treaty-adj-first-rejection.json']),
        action('录入修正贡献额并保存','cedant','延续前步已创建的本轮31草稿并核对归属；录入本次调整贡献额、期间和唯一备注并正常保存。提交另步在新ID明确并准备限定ADJUST_BILL Mock后执行。','正常保存后两段净额及科目均为本次调整贡献额1000，原单引用及签章/结算链接符合规则，原单不变；初次提交另步。',['ui-treaty-adj-first-rejection.json']),
        action('首次提交修正账单并核对待确认','cedant','本笔精确ADJUST_BILL Mock准备后，正常050中文页面初次提交31，按实际机构审核权限执行；提交后重新查询活动normal。','record_no允许NULL，父biz_no为A001；初始TREATY_BILL_PROCESS本轮父明细8/8且回调成功，新AB待确认3/3。新source3绑定新AB，不使用保存前normal。',['ui-treaty-adj-first-rejection.json']),
    ]+adjust_returns,snapshot_source_table=3,dependencies=['BILL-01'])
    settle=['ui-settlement-fixtures.json']
    add('SETTLE-01','settlement','结算单 录入保存与提交',[
        action('选择可结算的已确认账单','cedant','从结算工作台新增，按实际可结算条件选择币种、对手方和账单。','记录主体和对手方；结算链按付款方/收款方建模，经纪角色依据实际关系。',settle),
        action('填写结算信息与账单明细','cedant','核对收付款方向、币种、结算金额、付款期限和附件，添加本次独立测试账单。','主表/相关方task/明细关联正确；金额及币种一致。',settle),
        action('保存和重新打开核对','cedant','保存草稿并按本次编号重新打开，读取主要字段。','草稿状态0；不得复用历史SETTLE-001当作本次新增成功。',settle),
        action('提交结算单并进入发起方审核','cedant','双方草稿0且无本轮发起job时提交，核对本机构审核状态。','核对待审核1及实际审核级次；本地余额仅合成测试值。',settle),
        action('发起方一级审核','cedant','正常页面领取本轮任务，确认并提交下级审核。','050待审核1，review_level由1到2；后续审核另步核对。',settle),
        action('完成后续发起方审核并核对待确认','cedant','按现场级次完成后续审核，核对核心Mock回调。','原最终待确认3要求完整保留；真实record与资金独立验收。',settle),
    ],dependencies=['BILL-01'])
    add('SETTLE-02','settlement','结算单 接收方确认与上链边界',[
        action('切换实际接收方并领取','receiver','按结算收付款相关方登录，核对taskId对应的settlementId，不按固定经纪或再保身份推断。','任务归属与对手方正确。',settle),
        action('核对结算明细并提交接收方审核','receiver','核对账单明细、金额及单证后确认并提交机构审核。','仅确认进入机构审核1；后续审核及待结算另步核对。',settle),
        action('接收方一级审核','receiver','053正常领取本轮一级审核并确认提交下级。','接收方待审核1，review_level从1到2；最终审核另步。',settle),
        action('接收方最终审核并核对待结算','receiver','按现场完成最终审核，核对核心Mock及本地清分数据接收。','原双方待结算6验收保留；真实record与支付独立。',settle),
        action('核对结算上链record来源','database','用本次结算业务ID/交易定位record，确认新增、确认和派生账单更新均未维护otc_flag。','otc_flag均为NULL；Mock成功不能替代真实provider/service落库验证。',['http-results.json']),
        action('记录待结算终点','receiver','停在可核对的本地业务状态，登记实际链发送任务禁用及支付边界。','不执行真实收付款；如需测试登记/核销使用独立Mock任务。',settle),
    ],dependencies=['SETTLE-01'])
    add('SETTLE-03','settlement','结算单 审核拒绝与接收方退回后重提',[
        action('发起方审核不通过分支','cedant','独立结算草稿提交后，在实际机构审核页选择审核不通过。','待审核1→审核不通过2；发起方能按权限修改重提。',settle),
        action('接收方退回分支','receiver','另一笔独立待确认结算选择接收方退回，填写原因。','发送方状态5/接收方状态4按实际主从表核对；保存本轮快照。',settle),
        snapshot('记录结算退回快照',settle),
        action('发起方修改暂存与接收方只读隔离','cedant','发起方修改合法结算字段或明细并暂存，切换接收方读取退回详情。','实时V2、拒绝详情V1，来源固定5且source_id为主表settlementId。',settle),
        snapshot('核对结算暂存不改变旧快照',settle,compare=True),
        action('重新提交并再次退回','receiver','发起方按权限重提后由接收方再退回；分别核对快照保留与替换。','重提旧快照不清；二次退回旧Y新N且唯一有效。',settle),
    ],snapshot_source_table=5,dependencies=['SETTLE-01'])
    add('SETTLE-04','settlement','结算单 列表详情与缺快照读取',[
        action('核对正常桌面列表和金额','reinsurer','以1440×900打开结算列表，分别查询有快照和缺快照的自有测试单。','历史例有快照显示1201而非实时9001；缺快照列表显示实时9002；新例使用本轮变量。',settle),
        action('核对拒绝详情的主表来源映射','reinsurer','通过真实taskId打开详情，映射到settlementId，再按来源5读取快照；核对明细汇总和只读控件。','taskId不是source_id；结算明细和总额一致。',settle),
        action('核对缺快照详情明确错误','reinsurer','仅打开已有缺快照夹具；不删除真实快照来制造异常。','提示“拒绝状态的业务快照不存在，请联系管理员核查”；列表容错与详情必需快照分开。',settle),
    ],dependencies=['ENV-01'])
    add('CHAIN-01','onchain','普通业务 场内场外合约与账单来源核对',[
        action('切换真实provider链路并核对本地边界','local','按交接步骤切换9703业务Mock到真实provider；只处理本轮单据异步任务，使用本地pangu7545及service9545。','鉴权/业务校验/record写入真实；仅S3边界Mock，真实链发送任务禁用。',['otc-e2e-four-cases.json']),
        action('场内页面新增合约并追踪record','cedant','中文页面新增或复制本轮合约、保存、提交，逐笔定位core任务→provider→pangu/service→record。','本轮TREATY_IN新增record的otc_flag=0。',['otc-e2e-internal-treaty.json']),
        action('场内页面新增账单并追踪record','cedant','选择明确记录的完成合约前置，在页面新增账单、试算、保存提交；记录是否同一新合约。','本轮TREATY_BILL_IN新增record的otc_flag=0。',['otc-e2e-internal-bill.json']),
        action('场外正常鉴权发起合约','external','通过本地pangu正常token流程调用POST /v1/api/pangu/treaty/item；从合法本轮报文生成新的业务标识。','真实新增TREATY_IN record的otc_flag=1。',['otc-e2e-external-treaty.json']),
        action('场外发起引用新合约的账单','external','通过POST /v1/api/pangu/treaty/bill发送账单，引用前一步实际合约标识。','真实新增TREATY_BILL_IN record的otc_flag=1。',['otc-e2e-external-bill.json']),
        dict(name='按本次biz_id核对来源记录',role='database',kind='record',sources=['otc-e2e-four-cases.json'],instructions='必须输入本轮biz_id、msg_name与预期来源。只读查询，不以历史record替代新运行。',expected='记录存在且每条来源与本次调用一致；保留业务ID、recordID、交易及Mock边界。'),
    ],dependencies=['ENV-01'])
    add('CHAIN-02','onchain','普通与清结算交替调用 标记隔离',[
        action('普通场内外交替调用','external','本地分别走场内/场外普通入口，并记录每次真实新增record。','按当次调用记录0/1；同一业务创建场外、确认场内应分别1/0。',['http-results.json']),
        action('结算单新增确认退回及派生更新','receiver','在本地测试单上执行清结算分支；接口/任务入口及Mock范围来自交接，禁止推进历史批量任务。','结算新增/确认/退回、收付款派生及核销相关record的otc_flag均NULL。',['http-results.json']),
        dict(name='核对清结算新增record为NULL',role='database',kind='record',sources=['http-results.json'],instructions='输入本轮清结算biz_id和msg_name；expected_otc_flag必须null。',expected='记录非空，所有目标record为NULL，普通请求的0/1没有污染本请求。'),
    ],dependencies=['SETTLE-02'])
    return items


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    data=dict(version=1,created_at=datetime.now().astimezone().isoformat(),
              source_thread=dict(id='01a13982-32bb-7a30-a4e8-fbd302dd595c',title='backupdatafix及recordotcflag'),
              source_root=str(EVIDENCE),cases=cases(),
              authoring_status='需求与历史证据整理；写操作草稿须补齐本地页面采集，不冒称自动执行已通过')
    path=ROOT/'examples/reinsurance-local-selftest/catalog.json'
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'cases':len(data['cases']),'steps':sum(len(c['steps']) for c in data['cases']),'catalog':str(path)},ensure_ascii=False))


if __name__=='__main__':
    main()
