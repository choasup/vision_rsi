"""Training task definition: persistent clarification sessions and interface contracts."""
from contextlib import contextmanager
import json
import math
from pathlib import Path
import re
import sqlite3
import uuid

from .capability import task_id
from .llm import OpenAICompatibleClient

TYPES = {'image', 'image_list', 'video', 'text'}


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
    acceptance=contract.get('acceptance',{})
    if not isinstance(acceptance,dict) or any(not isinstance(acceptance.get(k),str) or not acceptance[k].strip() for k in ('metric','evaluation_protocol')):
        errors.append('缺少验收指标或评测协议')
    threshold=acceptance.get('threshold') if isinstance(acceptance,dict) else None
    if isinstance(threshold,bool) or not isinstance(threshold,(int,float)) or not math.isfinite(threshold): errors.append('缺少有限数值验收阈值')
    if isinstance(acceptance,dict) and acceptance.get('direction') not in ('maximize','minimize'): errors.append('缺少指标方向')
    budget=contract.get('budget',{})
    if not isinstance(budget,dict) or not budget: errors.append('缺少资源预算')
    elif any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or x<0 for x in budget.values()): errors.append('预算必须是非负有限数值')
    if not isinstance(contract.get('assumptions'),list): errors.append('需记录 assumptions 列表（允许为空）')
    if not isinstance(contract.get('open_questions'),list): errors.append('需记录 open_questions 列表')
    elif contract['open_questions']: errors.extend('待澄清: '+str(q) for q in contract['open_questions'])
    if 'example_input' not in contract or 'example_output' not in contract: errors.append('需提供输入/输出示例')
    elif not errors:
        try:
            validate_sample(contract,contract['example_input'])
            validate_schema(contract['output_schema'],contract['example_output'])
        except ValueError as error: errors.append('示例不符合接口: '+str(error))
    return errors


def validate_schema(schema,value,path='output'):
    # Supported schema subset, deliberately rejects unsupported constraints.
    allowed={'type','properties','required','items','description','enum','additionalProperties','minimum','maximum'}
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
                if not isinstance(uri,str) or not uri or '://' in uri: raise ValueError(name+': local file uri required')
    return {'valid':True,'media_decoded':False,'note':'协议校验，不代表文件可读取或模型具备对应能力。'}


class Sessions:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.root/'sessions.sqlite3',timeout=10)
        try:
            with db:
                db.execute('CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,task TEXT,turns TEXT,versions TEXT,pending INTEGER)')
                yield db
        finally: db.close()
    def create(self,name,goal):
        task_id(name)
        if not isinstance(goal,str) or not goal.strip(): raise ValueError('goal is required')
        session=uuid.uuid4().hex
        with self.db() as db: db.execute('INSERT INTO sessions VALUES (?,?,?,?,0)',(session,name,json.dumps([{'role':'user','content':goal}],ensure_ascii=False),'[]'))
        return self.show(session)
    def show(self,session):
        with self.db() as db: row=db.execute('SELECT * FROM sessions WHERE id=?',(session,)).fetchone()
        if not row: raise ValueError('Unknown session')
        versions=json.loads(row[3]); latest=versions[-1] if versions else None
        return {'session_id':row[0],'task_id':row[1],'turns':json.loads(row[2]),'versions':versions,'pending_request':bool(row[4]),'status':'ready_for_harness' if latest and not latest['issues'] else 'clarifying'}
    def define(self,session,contract,origin='user'):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT versions,pending FROM sessions WHERE id=?',(session,)).fetchone()
            if not row: raise ValueError('Unknown session')
            if row[1]: raise ValueError('Request in progress; do not overwrite contract')
            versions=json.loads(row[0]); versions.append({'version':len(versions)+1,'origin':origin,'contract':contract,'issues':issues(contract)})
            db.execute('UPDATE sessions SET versions=? WHERE id=?',(json.dumps(versions,ensure_ascii=False,allow_nan=False),session))
        return self.show(session)
    def clarify(self,session,config,message=None):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT turns,versions,pending FROM sessions WHERE id=?',(session,)).fetchone()
            if not row: raise ValueError('Unknown session')
            if row[2]: raise RuntimeError('Previous API outcome uncertain; no automatic retry')
            turns=json.loads(row[0]);versions=json.loads(row[1])
            if message: turns.append({'role':'user','content':message})
            db.execute('UPDATE sessions SET turns=?,pending=1 WHERE id=?',(json.dumps(turns,ensure_ascii=False),session))
        prompt={'instruction':'Define a vision training task interface by clarifying user requirements. Use the user's language for explanations and questions. Ask at most five critical questions per turn, record secondary choices as explicit assumptions rather than repeatedly asking. Return JSON contract ONLY with goal, inputs, output_schema, acceptance, budget, assumptions, open_questions, example_input, example_output. Do not invent thresholds or budget, do not weaken previous requirements; put missing facts in open_questions. Inputs are named fields: type image/image_list/video/text, required boolean. image_list requires min_items,max_items,semantics=joint. video requires processing:{sampling,temporal,audio}. Output schema subset: type,properties,required,items,description,enum,additionalProperties,minimum,maximum. Acceptance:{metric,threshold,direction=maximize/minimize,evaluation_protocol}. budget: numeric resource limits. example_input:{sample_id,inputs:{field:{type,uri or items:[{uri}] or value}}}. Joint multi-image is one sample, batch is multiple samples. Never imply training is implemented or performed.', 'turns':turns,'previous_contract':versions[-1]['contract'] if versions else None}
        response=OpenAICompatibleClient(dict(config,**({'thinking':'disabled'} if config.get('model')=='deepseek-flash' else {}))).complete([{'role':'user','content':json.dumps(prompt,ensure_ascii=False)}],max_tokens=3072)
        text=response['content'].strip()
        if text.startswith('```'): text=text.split('\n',1)[1].rsplit('```',1)[0]
        try: contract=json.loads(text); errors=issues(contract)
        except (ValueError,TypeError,KeyError,AttributeError) as error: contract={};errors=['解析失败: '+type(error).__name__]
        with self.db() as db:
            versions.append({'version':len(versions)+1,'origin':'llm_draft','contract':contract,'issues':errors,'usage':response.get('usage',{})})
            turns.append({'role':'assistant','content':json.dumps({'contract':contract,'issues':errors},ensure_ascii=False)})
            db.execute('UPDATE sessions SET turns=?,versions=?,pending=0 WHERE id=?',(json.dumps(turns,ensure_ascii=False),json.dumps(versions,ensure_ascii=False),session))
        return self.show(session)
