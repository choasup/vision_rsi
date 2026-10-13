"""Training task definition: persistent clarification sessions and interface contracts."""
from contextlib import contextmanager
import json
import math
from pathlib import Path
import re
import sqlite3
import uuid

from .capability import task_id
from .llm import OpenAICompatibleClient,LLMNotDispatched

TYPES = {'image', 'image_list', 'video', 'text'}
EVENT_PROTOCOL = 'vision-rsi/event_micro_f1/v1'
GPU_BUDGET_QUESTION = '首轮真实训练最多允许多少 GPU 小时？'
DEFAULT_EXPERIMENT_GPU_HOURS = 100


def default_experiment_budget(contract):
    """Apply the project default to new contracts, never rewrite saved ledgers."""
    if not isinstance(contract,dict):return contract
    budget=contract.get('budget')
    if budget is not None and not isinstance(budget,dict):return contract
    if isinstance(budget,dict) and 'gpu_hours' in budget:return contract
    result=dict(contract,budget=dict(budget or {},gpu_hours=DEFAULT_EXPERIMENT_GPU_HOURS),
                gpu_budget_scope='experiment')
    questions=result.get('open_questions')
    if isinstance(questions,list):
        result['open_questions']=[q for q in questions if q!=GPU_BUDGET_QUESTION]
    return result


def brief_questions(contract):
    """Only the four user decisions; implementation defaults are not questions."""
    questions=[]
    if not contract.get('inputs'):
        questions.append('模型接收什么输入？例如单张图片。')
    schema=contract.get('output_schema') or {}
    if not isinstance(schema,dict) or not schema.get('properties'):
        questions.append('希望模型输出什么？例如整张图片属于猫还是狗。')
    source=contract.get('data_source')
    if not isinstance(source,dict) or source.get('kind') not in ('local','public') or not isinstance(source.get('location'),str) or not source['location'].strip():
        questions.append('数据来自哪里？请给出已有数据路径，或说明允许使用哪些公开数据。')
    acceptance=contract.get('acceptance') or {}
    if not isinstance(acceptance,dict) or not acceptance.get('metric') or not acceptance.get('evaluation_protocol'):
        questions.append('希望怎样验证效果？不知道目标数值时，可以先跑基线看结果。')
    elif acceptance.get('threshold') is None and acceptance.get('mode')!='baseline':
        questions.append('验证目标是多少？也可以选择先跑基线，不预设达标数值。')
    return questions


def task_questions(contract):
    """New briefs use four fields; older saved contracts remain readable."""
    if 'data_source' in contract:
        return brief_questions(contract)
    questions=contract.get('open_questions')
    return [question for question in questions if isinstance(question,str) and question!=GPU_BUDGET_QUESTION] if isinstance(questions,list) else []


def interface_issues(contract):
    """Exploratory interface builds need no final acceptance threshold."""
    errors=issues(contract)
    acceptance=contract.get('acceptance') if isinstance(contract,dict) else None
    if isinstance(acceptance,dict) and acceptance.get('mode')=='baseline' and acceptance.get('threshold') is None:
        errors=[error for error in errors if error not in ('缺少有限数值验收阈值','事件F1验收阈值需在0..1内')]
    return [error for error in errors if '预算' not in error and not error.startswith('待澄清:')]


def normalize_contract(value):
    """Accept the common model envelope without discarding the actual contract."""
    for _ in range(5):
        if isinstance(value,dict) and isinstance(value.get('contract'),dict) and 'goal' not in value:
            value=value['contract']
        else: break
    return value


def definition_status(contract, errors):
    if not errors: return 'ready_for_harness'
    essential=[e for e in errors if not e.startswith('待澄清:') and '预算' not in e]
    return 'task_defined' if not essential else 'clarifying'


def unit_interval(value):
    return (not isinstance(value,bool) and isinstance(value,(int,float))
            and math.isfinite(value) and 0<=value<=1)


def issues(contract):
    errors=[]
    if not isinstance(contract,dict): return ['contract 必须为对象']
    if not isinstance(contract.get('goal'),str) or not contract['goal'].strip(): errors.append('缺少 goal')
    inputs=contract.get('inputs')
    if not isinstance(inputs,dict) or not inputs: errors.append('缺少命名 inputs 定义'); inputs={}
    for name,field in inputs.items():
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',name) or not isinstance(field,dict):
            errors.append('非法输入字段'); continue
        if field.get('type') not in TYPES or not isinstance(field.get('required'),bool): errors.append(name+': 缺少类型/required')
        if field.get('type')=='image_list':
            bounds=(field.get('min_items'),field.get('max_items'))
            if any(isinstance(x,bool) or not isinstance(x,int) for x in bounds) or not 1<=bounds[0]<=bounds[1]: errors.append(name+': 需明确多图数量范围')
            if field.get('semantics')!='joint': errors.append(name+': 需声明 joint 联合理解；批量另用样本清单')
        if field.get('type')=='video':
            policy=field.get('processing',{})
            if not isinstance(policy,dict) or any(not isinstance(policy.get(k),str) or not policy[k].strip() for k in ('sampling','temporal','audio')):
                errors.append(name+': 需明确视频采样、时序与音频处理')
    schema=contract.get('output_schema')
    if not isinstance(schema,dict) or schema.get('type')!='object' or not isinstance(schema.get('properties'),dict) or not schema['properties']:
        errors.append('需定义 object output_schema 及 properties')
    else:
        try: validate_schema_definition(schema)
        except ValueError as error: errors.append('输出接口无效: '+str(error))
    acceptance=contract.get('acceptance',{})
    if not isinstance(acceptance,dict) or any(not isinstance(acceptance.get(k),str) or not acceptance[k].strip() for k in ('metric','evaluation_protocol')):
        errors.append('缺少验收指标或评测协议')
    threshold=acceptance.get('threshold') if isinstance(acceptance,dict) else None
    if isinstance(threshold,bool) or not isinstance(threshold,(int,float)) or not math.isfinite(threshold): errors.append('缺少有限数值验收阈值')
    if isinstance(acceptance,dict) and acceptance.get('direction') not in ('maximize','minimize'): errors.append('缺少指标方向')
    if isinstance(acceptance,dict):
        if acceptance.get('evaluation_protocol')==EVENT_PROTOCOL:
            if acceptance.get('metric')!='event_micro_f1' or acceptance.get('direction')!='maximize':
                errors.append('事件评测协议要求 event_micro_f1/maximize')
            if not unit_interval(threshold):errors.append('事件F1验收阈值需在0..1内')
            iou=acceptance.get('iou_threshold')
            if not unit_interval(iou) or iou==0:errors.append('事件评测需明确0< iou_threshold <=1')
            properties=schema.get('properties') if isinstance(schema,dict) else None
            if not isinstance(properties,dict) or 'events' not in properties:
                errors.append('事件评测输出需定义 events 字段')
    budget=contract.get('budget',{})
    if not isinstance(budget,dict) or not budget: errors.append('缺少资源预算')
    elif any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or x<0 for x in budget.values()): errors.append('预算必须是非负有限数值')
    if not isinstance(contract.get('assumptions'),list): errors.append('需记录 assumptions 列表（允许为空）')
    if not isinstance(contract.get('open_questions'),list) or any(not isinstance(q,str) for q in contract.get('open_questions',[])): errors.append('需记录 open_questions 列表（元素必须为字符串）')
    elif contract['open_questions']: errors.extend('待澄清: '+str(q) for q in contract['open_questions'])
    if 'example_input' not in contract or 'example_output' not in contract: errors.append('需提供输入/输出示例')
    else:
        try:
            validate_sample(contract,contract['example_input'])
            validate_schema(contract['output_schema'],contract['example_output'])
        except (ValueError, KeyError, TypeError, AttributeError) as error: errors.append('示例不符合接口: '+str(error))
    return errors


def validate_schema_definition(schema, path='output'):
    allowed={'type','properties','required','items','description','enum','additionalProperties','minimum','maximum','minItems','maxItems'}
    if not isinstance(schema,dict) or set(schema)-allowed:
        raise ValueError(path+': unsupported schema keyword')
    kind=schema.get('type')
    if kind not in ('object','array','string','boolean','number','integer','null'):
        raise ValueError(path+': unknown schema type')
    if 'enum' in schema and (not isinstance(schema['enum'],list) or not schema['enum']):
        raise ValueError(path+': enum must be a nonempty list')
    if kind=='object':
        props=schema.get('properties',{})
        required=schema.get('required',[])
        if not isinstance(props,dict) or any(not isinstance(k,str) for k in props):
            raise ValueError(path+': invalid properties')
        if not isinstance(required,list) or any(not isinstance(k,str) or k not in props for k in required):
            raise ValueError(path+': invalid required fields')
        if 'additionalProperties' in schema and not isinstance(schema['additionalProperties'],bool):
            raise ValueError(path+': additionalProperties must be boolean')
        for name,child in props.items(): validate_schema_definition(child,path+'.'+name)
    elif 'properties' in schema or 'required' in schema or 'additionalProperties' in schema:
        raise ValueError(path+': object constraints on another type')
    if kind=='array':
        validate_schema_definition(schema.get('items'),path+'[]')
        for key in ('minItems','maxItems'):
            if key in schema and (isinstance(schema[key],bool) or not isinstance(schema[key],int) or schema[key]<0):
                raise ValueError(path+': invalid array length bound')
        if schema.get('minItems',0)>schema.get('maxItems',math.inf):raise ValueError(path+': reversed array length bounds')
    elif any(key in schema for key in ('items','minItems','maxItems')): raise ValueError(path+': array constraints require array')
    for key in ('minimum','maximum'):
        if key in schema:
            bound=schema[key]
            if kind not in ('number','integer') or isinstance(bound,bool) or not isinstance(bound,(int,float)) or not math.isfinite(bound):
                raise ValueError(path+': invalid numeric bounds')
    if schema.get('minimum',-math.inf)>schema.get('maximum',math.inf):
        raise ValueError(path+': reversed bounds')


def validate_schema(schema,value,path='output'):
    validate_schema_definition(schema,path)
    # Supported schema subset, deliberately rejects unsupported constraints.
    allowed={'type','properties','required','items','description','enum','additionalProperties','minimum','maximum','minItems','maxItems'}
    if not isinstance(schema,dict) or set(schema)-allowed: raise ValueError(path+': unsupported schema keyword')
    kind=schema.get('type')
    ok={'object':isinstance(value,dict),'array':isinstance(value,list),'string':isinstance(value,str),
        'boolean':isinstance(value,bool),'number':not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value),
        'integer':not isinstance(value,bool) and isinstance(value,int),'null':value is None}
    if kind not in ok or not ok[kind]: raise ValueError(path+': type mismatch')
    if 'enum' in schema and value not in schema['enum']: raise ValueError(path+': enum mismatch')
    if kind in ('number','integer'):
        if value<schema.get('minimum',-math.inf) or value>schema.get('maximum',math.inf): raise ValueError(path+': numeric bounds')
    if kind=='object':
        props=schema.get('properties',{})
        if any(k not in value for k in schema.get('required',[])): raise ValueError(path+': required field missing')
        if schema.get('additionalProperties') is False and set(value)-set(props): raise ValueError(path+': unknown field')
        for key,item in value.items():
            if key in props: validate_schema(props[key],item,path+'.'+key)
    if kind=='array':
        if not schema.get('minItems',0)<=len(value)<=schema.get('maxItems',math.inf):raise ValueError(path+': array length bounds')
        if not isinstance(schema.get('items'),dict): raise ValueError(path+': array items schema required')
        for index,item in enumerate(value): validate_schema(schema['items'],item,f'{path}[{index}]')


def validate_sample(contract,sample):
    if not isinstance(sample,dict) or not isinstance(sample.get('sample_id'),str) or not sample['sample_id']: raise ValueError('sample_id required')
    values=sample.get('inputs')
    if not isinstance(values,dict) or set(values)-set(contract['inputs']): raise ValueError('unknown inputs')
    for name,field in contract['inputs'].items():
        if name not in values:
            if field['required']: raise ValueError(name+': required')
            continue
        value=values[name]; kind=field['type']
        if not isinstance(value,dict) or value.get('type')!=kind: raise ValueError(name+': input type mismatch')
        if kind=='text':
            if not isinstance(value.get('value'),str): raise ValueError(name+': text value required')
        else:
            items=value.get('items') if kind=='image_list' else [value]
            if not isinstance(items,list) or kind=='image_list' and not field['min_items']<=len(items)<=field['max_items']: raise ValueError(name+': invalid item count')
            for item in items:
                uri=item.get('uri') if isinstance(item,dict) else None
                if not isinstance(uri,str) or not uri or '://' in uri and not uri.startswith('file:///'): raise ValueError(name+': local file uri required')
    return {'valid':True,'media_decoded':False,'note':'协议校验，不代表文件可读取或模型具备对应能力。'}


class Sessions:
    def __init__(self,root,read_only=False):
        self.root=Path(root);self.read_only=read_only
        if read_only:
            if not (self.root/'sessions.sqlite3').is_file():raise ValueError('Session ledger missing')
        else:self.root.mkdir(parents=True,exist_ok=True)
    @contextmanager
    def db(self):
        if self.read_only:
            from urllib.parse import quote
            path=quote(str((self.root/'sessions.sqlite3').resolve()).replace('\\','/'),safe='/:')
            db=sqlite3.connect('file:'+path+'?mode=ro',uri=True,timeout=10)
            try:yield db
            finally:db.close()
            return
        db=sqlite3.connect(self.root/'sessions.sqlite3',timeout=10)
        try:
            with db:
                db.execute('CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,task TEXT,turns TEXT,versions TEXT,pending INTEGER)')
                db.execute('CREATE TABLE IF NOT EXISTS clarification_responses(id TEXT PRIMARY KEY,session TEXT,response TEXT)')
                db.execute('CREATE TABLE IF NOT EXISTS clarification_requests(id TEXT PRIMARY KEY,session TEXT,context TEXT,state TEXT,response_ids TEXT)')
                yield db
        finally: db.close()
    def list(self):
        with self.db() as db:
            rows = db.execute('SELECT id FROM sessions ORDER BY rowid DESC').fetchall()
        return [{'session_id': r['session_id'], 'task_id': r['task_id'], 'status': r['status'],
                 'contract_version': len(r['versions'])} for r in (self.show(row[0]) for row in rows)]

    def start(self,name,goal=None,new_session=False,session_id=None):
        """Atomically resume a task or explicitly create another conversation."""
        task_id(name)
        if new_session and session_id:
            raise ValueError('--new-session cannot be combined with --session-id')
        selected=None;created=False;matches=[]
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if session_id:
                row=db.execute('SELECT task FROM sessions WHERE id=?',(session_id,)).fetchone()
                if not row or row[0]!=name:
                    raise ValueError('所选会话不存在或不属于当前 task-id。')
                selected=session_id
            elif not new_session:
                matches=[row[0] for row in db.execute('SELECT id FROM sessions WHERE task=? ORDER BY rowid DESC',(name,))]
                if len(matches)==1:selected=matches[0]
            if not selected and (new_session or not matches):
                if not isinstance(goal,str) or not goal.strip():
                    return {'status':'goal_required'}
                selected=uuid.uuid4().hex;created=True
                db.execute('INSERT INTO sessions VALUES (?,?,?,?,0)',
                           (selected,name,json.dumps([{'role':'user','content':goal}],ensure_ascii=False),'[]'))
        if selected:
            return {'status':'created' if created else 'resumed','session':self.show(selected)}
        choices=[]
        for candidate in matches:
            saved=self.show(candidate)
            latest=saved['versions'][-1] if saved['versions'] else {}
            contract=latest.get('proposed_contract',latest.get('contract',{}))
            initial=saved['turns'][0]['content'] if saved['turns'] else ''
            last_user=next((turn['content'] for turn in reversed(saved['turns']) if turn['role']=='user'),'')
            choices.append({'session_id':candidate,'task_id':name,'status':saved['status'],
                            'contract_version':len(saved['versions']),'goal':contract.get('goal') or initial,
                            'last_user_message':last_user,'pending_request':saved['pending_request']})
        return {'status':'selection_required','task_id':name,'sessions':choices}

    def create(self,name,goal):
        task_id(name)
        if not isinstance(goal,str) or not goal.strip(): raise ValueError('goal is required')
        session=uuid.uuid4().hex
        with self.db() as db: db.execute('INSERT INTO sessions VALUES (?,?,?,?,0)',(session,name,json.dumps([{'role':'user','content':goal}],ensure_ascii=False),'[]'))
        return self.show(session)
    def show(self,session):
        with self.db() as db:
            row=db.execute('SELECT * FROM sessions WHERE id=?',(session,)).fetchone()
            pending=db.execute("SELECT id,response_ids FROM clarification_requests WHERE session=? AND state='pending' ORDER BY rowid DESC LIMIT 1",(session,)).fetchone()
            if row and row[4]==2:
                pending=db.execute("SELECT id,response_ids FROM clarification_requests WHERE session=? AND state='not_dispatched' ORDER BY rowid DESC LIMIT 1",(session,)).fetchone()
            unsettled=[item[0] for item in db.execute("SELECT id FROM clarification_requests WHERE session=? AND state IN ('abandoned','recovered')",(session,))]
        if not row: raise ValueError('Unknown session')
        versions=json.loads(row[3])
        for version in versions:
            original=version['contract']
            normalized=normalize_contract(original)
            if normalized != original:
                version['raw_contract']=original
                version['contract']=normalized
                version['issues']=issues(normalized)
        latest=versions[-1] if versions else None
        status='requirements_review' if latest and latest.get('review_required') else definition_status(latest['contract'],latest['issues']) if latest else 'clarifying'
        if row[4]==2:status='requirements_not_dispatched'
        return {'session_id':row[0],'task_id':row[1],'turns':json.loads(row[2]),'versions':versions,'pending_request':bool(row[4]),
                'clarification_not_dispatched':row[4]==2,'api_outcome_uncertain':row[4]==1,
                'pending_request_id':pending[0] if pending else None,'pending_response_count':len(json.loads(pending[1])) if pending else 0,'unsettled_api_request_ids':unsettled,'status':status}
    def define(self,session,contract,origin='user'):
        contract=normalize_contract(contract)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT versions,pending FROM sessions WHERE id=?',(session,)).fetchone()
            if not row: raise ValueError('Unknown session')
            if row[1] and not (row[1]==2 and origin=='user'): raise ValueError('Request in progress; do not overwrite contract')
            versions=json.loads(row[0])
            if not versions:contract=default_experiment_budget(contract)
            version={'version':len(versions)+1,'origin':origin,'contract':contract,'issues':issues(contract)}
            if row[1]==2:version['supersedes_not_dispatched_requirements']=True
            versions.append(version)
            db.execute('UPDATE sessions SET versions=?,pending=0 WHERE id=?',(json.dumps(versions,ensure_ascii=False,allow_nan=False),session))
        return self.show(session)
    def set_gpu_budget(self,session,hours):
        """Record explicit initial authorization without another model call."""
        try:valid=type(hours) in (int,float) and hours>0 and math.isfinite(hours) and math.isfinite(hours*3600)
        except (OverflowError,TypeError):valid=False
        if not valid:raise ValueError('GPU hours must be a positive finite executable duration')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT turns,versions,pending FROM sessions WHERE id=?',(session,)).fetchone()
            if not row:raise ValueError('Unknown session')
            if row[2]:raise ValueError('Request in progress; do not overwrite contract')
            turns=json.loads(row[0]);versions=json.loads(row[1])
            if not versions:raise ValueError('Define the task interface before setting its GPU budget')
            latest=versions[-1]
            if latest.get('review_required'):raise ValueError('Resolve the pending requirements draft before setting a budget')
            contract=normalize_contract(json.loads(json.dumps(latest['contract'])))
            if not isinstance(contract,dict) or not isinstance(contract.get('open_questions'),list):
                raise ValueError('Define a valid task question list before setting its budget')
            budget=contract.get('budget')
            if budget is not None and not isinstance(budget,dict):raise ValueError('Existing budget is malformed')
            budget=dict(budget or {})
            if budget.get('gpu_hours') is not None and budget['gpu_hours']!=hours:
                raise ValueError('GPU budget already defined; this command cannot revise or reset an existing execution budget')
            budget['gpu_hours']=hours;contract['budget']=budget
            # Only this exact system-owned question is resolved. Do not guess
            # which unrelated natural-language requirements can be discarded.
            contract['open_questions']=[q for q in contract.get('open_questions',[]) if q!=GPU_BUDGET_QUESTION]
            if contract!=latest['contract']:
                versions.append({'version':len(versions)+1,'origin':'user_gpu_budget','contract':contract,'issues':issues(contract)})
                turns.append({'role':'user','content':'设置初始 GPU 预算上限为 '+str(hours)+' GPU 小时。'})
                db.execute('UPDATE sessions SET turns=?,versions=? WHERE id=?',
                           (json.dumps(turns,ensure_ascii=False),json.dumps(versions,ensure_ascii=False,allow_nan=False),session))
        return self.show(session)

    @contextmanager
    def request_lock(self,session):
        import hashlib
        from .campaign import lease
        path=self.root/('clarification-'+hashlib.sha256(str(session).encode()).hexdigest()+'.lock')
        with lease(path):yield

    def clarify(self,session,config,message=None):
        with self.request_lock(session):return self._clarify(session,config,message)

    def _clarify(self,session,config,message=None):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT turns,versions,pending FROM sessions WHERE id=?',(session,)).fetchone()
            if not row: raise ValueError('Unknown session')
            if row[2] not in (0,2): raise RuntimeError('Previous API outcome uncertain; no automatic retry')
            client=OpenAICompatibleClient(dict(config,**({'thinking':'disabled'} if config.get('model')=='deepseek-flash' else {})))
            client.validate_config()
            turns=json.loads(row[0]);versions=json.loads(row[1])
            if message: turns.append({'role':'user','content':message})
            db.execute('UPDATE sessions SET turns=?,pending=1 WHERE id=?',(json.dumps(turns,ensure_ascii=False),session))
            request_id=uuid.uuid4().hex
            context={'turns':turns,'versions':versions}
            db.execute('INSERT INTO clarification_requests VALUES (?,?,?,?,?)',(request_id,session,json.dumps(context,ensure_ascii=False),'pending','[]'))
        prompt={'instruction':'Extract the actual user task, not the act of defining an interface. Preserve all explicit goals and constraints across turns. Ask only for ambiguity that changes the task. Never ask for architecture, optimizer, precision, latency constraints or dataset version unless the user makes them relevant; select reasonable defaults and record assumptions. Budget is an execution prerequisite, not a reason to ask the user to restate the task. Return the contract object directly, never wrap it in contract or issues. Use the language of the user for explanations and questions. Ask only one critical question per turn in plain language, with a concrete example or suggested choices when helpful. Keep other missing facts recorded for later turns; do not invent answers or thresholds. Record secondary implementation choices as explicit assumptions rather than repeatedly asking. Return JSON contract ONLY with goal, inputs, output_schema, acceptance, budget, assumptions, open_questions, example_input, example_output, data_source, and assistant_message (a short plain-language reply). Do not invent thresholds or non-default budgets, do not weaken previous requirements; put missing facts in open_questions. Inputs are named fields: type image/image_list/video/text, required boolean. image_list requires min_items,max_items,semantics=joint. video requires processing:{sampling,temporal,audio}. Output schema subset: type,properties,required,items,description,enum,additionalProperties,minimum,maximum,minItems,maxItems. Acceptance:{metric,threshold,direction=maximize/minimize,evaluation_protocol}. budget: numeric resource limits. example_input:{sample_id,inputs:{field:{type,uri or items:[{uri}] or value}}}. Joint multi-image is one sample, batch is multiple samples. Never imply training is implemented or performed.', 'turns':[t for t in turns if t['role']=='user'],'previous_contract':normalize_contract(versions[-1]['contract']) if versions else None}
        active=normalize_contract(versions[-1]['contract']) if versions else {}
        previous=normalize_contract(versions[-1].get('proposed_contract',active)) if versions else {}
        prompt['previous_contract']=previous
        prompt['active_contract']=active
        prompt['recent_dialogue']=turns[-12:]
        prompt['brief_rules']='Collect ONLY input, output, data source and validation goal. Ask only missing fields; preserve answered facts from the working draft and dialogue. Select model, optimizer, data split and interface representation as explicit defaults, never user questions. Add data_source: {kind: local/public/unknown, location: user supplied path or public dataset scope, download_allowed: boolean}. Never infer download permission; public data selection and download are separate decisions. Add acceptance.mode: target or baseline. If the user does not know a target, recommend baseline and use mode=baseline, threshold=null; this is exploration, never acceptance or training authorization. Once the four fields are known, set open_questions to [] and move to experiment preparation. Do not ask about model choice, GPU hours or numerical acceptance targets during baseline clarification. Preserve explicit target thresholds exactly.'
        questions=task_questions(previous)
        prompt['reply_context']={'question_shown_to_user':questions[0] if questions and not versions[-1].get('review_required') else None,
                                 'user_reply':message,
                                 'previous_explanation':versions[-1].get('assistant_message') if versions else None,
                                 'instruction':'Interpret short replies such as 是/否 as answers to question_shown_to_user, not as confirmation of a requirements draft. Incorporate the answer, record the resolved fact in assumptions, and remove a resolved question from open_questions. If the answer does not resolve it, explain exactly what remains ambiguous instead of repeating the same question unchanged.'}
        from .task_adapters import training_adapter
        prompt['execution_context']={'training_adapter':training_adapter(previous),
                                     'execution_checked':False,'training_started':False,
                                     'pending_requirements_review':bool(versions and versions[-1].get('review_required')),
                                     'instruction':'This call only clarifies requirements. A task definition or user budget is not evidence that execution is ready. Do not say ready to start, can execute, or training started. Only a program-side readiness/preflight result can establish the next executable action. For an unsupported task, explain the missing backend and do not ask the user to repeatedly confirm it.'}
        prompt['change_policy']='Preserve established goal wording, input/output interface, acceptance values and budget exactly unless the user explicitly requests a change. Put implementation choices in assumptions. Do not paraphrase unchanged goal/protocol descriptions. Structural changes are reviewed separately before execution.'
        prompt['available_evaluation_defaults']={'video_events':{
            'use_only_if_matching_user_task':True,'metric':'event_micro_f1','direction':'maximize',
            'evaluation_protocol':EVENT_PROTOCOL,'metric_scale':'0..1',
            'acceptance_extra_field':'iou_threshold, finite and greater than 0 up to 1',
            'matching':'Same sample and label, temporal IoU, maximum-cardinality one-to-one matching',
            'output':'object with events array; each event has label, start_seconds, end_seconds',
            'selection_policy':'Use only when the user accepts this metric semantics. Never replace an explicit metric or protocol. If event matching is unspecified, explain this proposed protocol and record its IoU choice as an assumption; preserve established acceptance exactly. Never invent the F1 target.',
            'implementation_scope':'Standalone evaluator only; no video model training or inference adapter implemented.'}}
        prompt['missing_gpu_budget_question']='Do not ask for GPU budget. New tasks default to 100 GPU-hours per experiment; preserve any explicit user budget and all saved task budgets.'
        prompt['conversation_rules']='Include an assistant_message string alongside the contract fields: a short reply in the user language addressing their latest message. When the user asks for advice or says they do not know, explain concrete options and a recommended next step instead of repeating the same question. Advice is not user authorization: never invent or set a budget or acceptance threshold from a request for advice. GPU budget is needed only before execution; use the configured 100 GPU-hour per-experiment default for new tasks without an explicit budget; never put GPU budget in open_questions, and do not ask for GPU hours during initial requirements clarification. For ambiguous recognition tasks such as cat/dog recognition, ask whether the user wants a class for the whole image or boxes around individual animals before selecting classification or detection. Never infer detection solely because a COCO adapter exists. Explain unsupported execution honestly; advice must not claim training ran or authorize training.'
        prompt['format_rules']='output_schema MUST have type=object and nonempty properties; place detection lists inside a detections property, never at the root. assumptions and open_questions MUST be lists of strings, never dictionaries. Video processing sampling, temporal, audio MUST each be nonempty strings; use audio="ignore" for no audio, never false. budget MUST be an object mapping resource names to numeric limits, for example {"gpu_hours":10}, or null when missing. A bare number, string or list is invalid. Never infer GPU hours from an ambiguous wall-clock training duration. For a new task without an explicit GPU budget, leave budget null for the host to apply 100 GPU-hours per experiment. Do not ask the user for budget. Examples must satisfy the exact interface. Batch means multiple samples, not image_list. Do not ask for batch size limits, model confidence filters, optimizer or architectural choices unless explicitly constrained by the user; record implementation defaults in assumptions. The inputs section describes INFERENCE-time per-sample inputs only. Training/validation/held-out datasets, annotation files, budgets, weights and evaluation protocols are training resources, NEVER required inference input fields unless the user explicitly requests them as per-sample inputs. Select conventional box coordinates as an assumption, never ask about JSON field names or coordinate syntax. Ask only unresolved task semantics (such as defect class taxonomy or event matching needed to define a metric), not internal representation choices. Resolve schema formatting internally; never ask the user to write JSON schemas.'
        from .detector import COCO_IDS
        prompt['available_adapter_defaults']={'coco_detection':{'use_only_if_matching_user_task':True,'inputs':{'image':{'type':'image','required':True}},'acceptance_metric':'box_AP','metric_units':'0..100','output':'object with detections array; each item has category_id (integer), bbox (4 numbers, COCO xywh pixels), score (0..1)','category_ids':list(COCO_IDS),'note':'80 COCO categories use sparse IDs in 1..90, NOT contiguous 1..80. These are optional implementation defaults, never override an explicit user interface. No claim of training, quality or other task adapter availability.'}}
        messages=[{'role':'system','content':'You define a visual Agent task interface from the user conversation. Follow these format and scope rules exactly: '+prompt['format_rules']},{'role':'user','content':json.dumps(prompt,ensure_ascii=False)}]
        responses=[];response_ids=[];first_draft=None
        for attempt in range(2):
            try:response=client.complete(messages,max_tokens=3072)
            except LLMNotDispatched as error:
                if responses:
                    return self._finish_response(session,request_id,turns,versions,responses,response_ids,first_draft,
                                                 correction_not_dispatched=str(error))
                with self.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    current=db.execute('SELECT turns,versions,pending FROM sessions WHERE id=?',(session,)).fetchone()
                    if (not current or not current[2] or json.loads(current[0])!=turns
                            or json.loads(current[1])!=versions):
                        raise RuntimeError('Session context changed; unsent request remains recorded') from None
                    changed=db.execute('UPDATE clarification_requests SET state=? WHERE id=? AND session=? AND state=? AND response_ids=?',
                                       ('not_dispatched',request_id,session,'pending','[]'))
                    if changed.rowcount!=1:raise RuntimeError('Unsent request identity changed')
                    db.execute('UPDATE sessions SET pending=2 WHERE id=?',(session,))
                raise
            response_id=uuid.uuid4().hex
            responses.append(response);response_ids.append(response_id)
            with self.db() as db:
                db.execute('INSERT INTO clarification_responses VALUES (?,?,?)',(response_id,session,json.dumps(response,ensure_ascii=False)))
                db.execute('UPDATE clarification_requests SET response_ids=? WHERE id=? AND state=?',(json.dumps(response_ids),request_id,'pending'))
            # A bounded correction of a received schema is not a network retry.
            # Missing task facts and resource authorization must never be invented.
            try:
                text=response['content'].strip()
                if text.startswith('```'):
                    if '\n' not in text:raise ValueError('Incomplete fenced response')
                    text=text.split('\n',1)[1].rsplit('```',1)[0]
                draft=normalize_contract(json.loads(text))
                json.dumps(draft,allow_nan=False)
                if isinstance(draft,dict):draft.pop('assistant_message',None)
                if not attempt and isinstance(draft,dict):first_draft=draft
                formatting=[error for error in issues(draft) if error.startswith(('需定义 object','输出接口无效:','需记录 assumptions','需记录 open_questions','示例不符合接口:')) or '需明确视频采样、时序与音频处理' in error]
            except (ValueError,TypeError,KeyError,AttributeError):break
            if not formatting or attempt:break
            messages.extend([{'role':'assistant','content':response['content']},
                             {'role':'user','content':json.dumps({'instruction':'Correct these interface formatting errors only. Preserve goal, acceptance, budget, explicit input semantics and all user constraints exactly. Do not ask the user about schema fields. Return the complete corrected contract JSON only.','errors':formatting,'format_rules':prompt['format_rules']},ensure_ascii=False)}])
        return self._finish_response(session,request_id,turns,versions,responses,response_ids,first_draft)

    def _finish_response(self,session,request_id,turns,versions,responses,response_ids,first_draft,recovered=False,correction_not_dispatched=None):
        response=responses[-1]
        review=[];proposed=None;assistant_message=None
        try:
            if not isinstance(response.get('content'),str):raise ValueError('Model response has no contract text')
            text=response['content'].strip()
            if text.startswith('```'):
                if '\n' not in text:raise ValueError('Incomplete fenced response')
                text=text.split('\n',1)[1].rsplit('```',1)[0]
            contract=normalize_contract(json.loads(text))
            if not isinstance(contract,dict):raise ValueError('Model contract must be an object')
            json.dumps(contract,allow_nan=False)
            if versions:
                working=versions[-1].get('proposed_contract',versions[-1]['contract'])
                if 'data_source' not in contract and 'data_source' in working:
                    # Omission is not a request to forget an answered source.
                    contract['data_source']=working['data_source']
            guidance=contract.pop('assistant_message',None)
            if isinstance(guidance,str) and guidance.strip():assistant_message=guidance.strip()
            if len(responses)>1:
                if any(contract.get(key)!=first_draft.get(key) for key in ('goal','acceptance','budget')):
                    raise ValueError('Schema correction changed task requirements')
                original_inputs=first_draft.get('inputs') or {};corrected_inputs=contract.get('inputs') or {}
                if set(corrected_inputs)!=set(original_inputs):raise ValueError('Schema correction changed input fields')
                for name,field in original_inputs.items():
                    corrected=corrected_inputs[name]
                    if not isinstance(field,dict) or not isinstance(corrected,dict):raise ValueError('Invalid corrected input')
                    for key in ('type','required','min_items','max_items','semantics'):
                        if corrected.get(key)!=field.get(key):raise ValueError('Schema correction changed input semantics')
                    if field.get('type')=='video' and isinstance(field.get('processing'),dict):
                        for key,value in field['processing'].items():
                            if isinstance(value,str) and value.strip() and corrected.get('processing',{}).get(key)!=value:
                                raise ValueError('Schema correction changed video policy')
            if not versions:
                contract=default_experiment_budget(contract)
            elif versions[-1]['contract'].get('gpu_budget_scope'):
                contract.setdefault('gpu_budget_scope',versions[-1]['contract']['gpu_budget_scope'])
                if contract.get('budget') is None:
                    contract['budget']=versions[-1]['contract']['budget']
            if contract.get('gpu_budget_scope')=='experiment' and isinstance(contract.get('open_questions'),list):
                contract['open_questions']=[q for q in contract['open_questions'] if q!=GPU_BUDGET_QUESTION]
            errors=issues(contract)
            if versions:
                from .requirements import changes
                previous=normalize_contract(versions[-1]['contract'])
                review=changes(previous,contract)
                if review:
                    proposed=contract;contract=previous
                    errors=issues(contract)+['待确认需求变更: '+change['path'] for change in review]
        except (ValueError,TypeError,KeyError,AttributeError) as error:
            assistant_message=None
            contract=normalize_contract(versions[-1]['contract']) if versions else first_draft or {}
            errors=issues(contract)+['解析失败: '+type(error).__name__+'；已保留上一版需求']
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT turns,versions,pending FROM sessions WHERE id=?',(session,)).fetchone()
            request=db.execute('SELECT state FROM clarification_requests WHERE id=? AND session=?',(request_id,session)).fetchone()
            if not current or not request or request[0]!='pending' or not current[2] or json.loads(current[0])!=turns or json.loads(current[1])!=versions:
                raise ValueError('Clarification context changed; recorded response was not applied')
            version={'version':len(versions)+1,'origin':'llm_draft','contract':contract,'issues':errors,'usage':response.get('usage',{})}
            if assistant_message:version['assistant_message']=assistant_message
            version.update(request_id=request_id,response_ids=response_ids,response_usage=[item.get('usage',{}) for item in responses],format_correction_attempted=len(responses)>1)
            if correction_not_dispatched:
                version['format_correction_not_dispatched']=correction_not_dispatched
                version['issues'].append('格式修正请求未发送: '+correction_not_dispatched)
            if recovered:version.update(recovered_from_pending=True,api_outcome_uncertain=True)
            if review:version.update(review_required=review,proposed_contract=proposed)
            versions.append(version)
            reply={'contract':contract,'issues':errors}
            if assistant_message:reply['assistant_message']=assistant_message
            turns.append({'role':'assistant','content':json.dumps(reply,ensure_ascii=False)})
            db.execute('UPDATE sessions SET turns=?,versions=?,pending=0 WHERE id=?',(json.dumps(turns,ensure_ascii=False),json.dumps(versions,ensure_ascii=False),session))
            db.execute('UPDATE clarification_requests SET state=? WHERE id=?',('recovered' if recovered else 'completed',request_id))
        return self.show(session)

    def resolve_request(self,session,request_id,abandon=False):
        if not isinstance(request_id,str) or not re.fullmatch('[0-9a-f]{32}',request_id):raise ValueError('Specify the exact pending request ID')
        with self.request_lock(session):
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT context,state,response_ids FROM clarification_requests WHERE id=? AND session=?',(request_id,session)).fetchone()
                if not row:raise ValueError('Unknown clarification request for this session')
                if row[1]!='pending':
                    already_resolved=row[1]=='abandoned' if abandon else row[1] in ('completed','recovered')
                    if already_resolved:return self.show(session)
                    raise ValueError('Request already resolved differently')
                context=json.loads(row[0]);ids=json.loads(row[2])
                current=db.execute('SELECT turns,versions,pending FROM sessions WHERE id=?',(session,)).fetchone()
                if not current or not current[2] or json.loads(current[0])!=context['turns'] or json.loads(current[1])!=context['versions']:
                    raise ValueError('Request context changed; resolution refused')
                if abandon:
                    db.execute("UPDATE clarification_requests SET state='abandoned' WHERE id=?",(request_id,))
                    db.execute('UPDATE sessions SET pending=0 WHERE id=?',(session,))
                else:
                    if not ids:raise ValueError('No recorded response to recover; use abandon-request to explicitly release local pending state. Remote API outcome/cost remains unknown.')
                    responses=[]
                    for identity in ids:
                        response=db.execute('SELECT response FROM clarification_responses WHERE id=? AND session=?',(identity,session)).fetchone()
                        if not response:raise ValueError('Recorded response missing')
                        responses.append(json.loads(response[0]))
            if abandon:return self.show(session)
            first=None
            try:
                text=responses[0]['content'].strip()
                if text.startswith('```'):text=text.split('\n',1)[1].rsplit('```',1)[0]
                first=normalize_contract(json.loads(text));json.dumps(first,allow_nan=False)
                if not isinstance(first,dict):first=None
            except (ValueError,TypeError,KeyError,AttributeError):first=None
            return self._finish_response(session,request_id,context['turns'],context['versions'],responses,ids,first,recovered=True)

    def accept(self,session,version):
        return self.review(session,version,True)

    def reject(self,session,version):
        return self.review(session,version,False)

    def review(self,session,version,accept):
        if isinstance(version,bool) or not isinstance(version,int) or version<1:raise ValueError('Specify the exact draft version to accept')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT turns,versions,pending FROM sessions WHERE id=?',(session,)).fetchone()
            if not row:raise ValueError('Unknown session')
            if row[2]:raise ValueError('API request is still pending or uncertain')
            versions=json.loads(row[1]);turns=json.loads(row[0])
            if not versions or versions[-1]['version']!=version or not versions[-1].get('review_required'):
                raise ValueError('Only the current pending requirements draft can be accepted')
            contract=versions[-1]['proposed_contract'] if accept else versions[-1]['contract']
            versions.append({'version':len(versions)+1,'origin':'user_accepted_model_draft' if accept else 'user_rejected_model_draft',
                             'reviewed_draft_version':version,'contract':contract,'issues':issues(contract)})
            turns.append({'role':'user','content':('接受' if accept else '拒绝')+'需求草案 v'+str(version)})
            db.execute('UPDATE sessions SET turns=?,versions=? WHERE id=?',(json.dumps(turns,ensure_ascii=False),json.dumps(versions,ensure_ascii=False,allow_nan=False),session))
        return self.show(session)


def validate_manifest(contract, path):
    results=[]; seen=set()
    for line_number,line in enumerate(Path(path).read_text(encoding='utf-8-sig').splitlines(),1):
        if not line.strip(): continue
        sample_id=None
        try:
            sample=json.loads(line)
            sample_id=sample.get('sample_id') if isinstance(sample,dict) else None
            validate_sample(contract,sample)
            if sample_id in seen: raise ValueError('Duplicate sample_id')
            seen.add(sample_id)
            results.append({'line':line_number,'sample_id':sample_id,'valid':True})
        except (ValueError,TypeError,KeyError) as error:
            results.append({'line':line_number,'sample_id':sample_id,'valid':False,'error':str(error)})
    return {'valid':bool(results) and all(r['valid'] for r in results),'samples':results,'media_decoded':False}
