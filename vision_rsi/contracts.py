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
    budget=contract.get('budget',{})
    if not isinstance(budget,dict) or not budget: errors.append('缺少资源预算')
    elif any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or x<0 for x in budget.values()): errors.append('预算必须是非负有限数值')
    if not isinstance(contract.get('assumptions'),list): errors.append('需记录 assumptions 列表（允许为空）')
    if not isinstance(contract.get('open_questions'),list): errors.append('需记录 open_questions 列表')
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
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.root/'sessions.sqlite3',timeout=10)
        try:
            with db:
                db.execute('CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,task TEXT,turns TEXT,versions TEXT,pending INTEGER)')
                db.execute('CREATE TABLE IF NOT EXISTS clarification_responses(id TEXT PRIMARY KEY,session TEXT,response TEXT)')
                yield db
        finally: db.close()
    def list(self):
        with self.db() as db:
            rows = db.execute('SELECT id FROM sessions ORDER BY rowid DESC').fetchall()
        return [{'session_id': r['session_id'], 'task_id': r['task_id'], 'status': r['status'],
                 'contract_version': len(r['versions'])} for r in (self.show(row[0]) for row in rows)]

    def create(self,name,goal):
        task_id(name)
        if not isinstance(goal,str) or not goal.strip(): raise ValueError('goal is required')
        session=uuid.uuid4().hex
        with self.db() as db: db.execute('INSERT INTO sessions VALUES (?,?,?,?,0)',(session,name,json.dumps([{'role':'user','content':goal}],ensure_ascii=False),'[]'))
        return self.show(session)
    def show(self,session):
        with self.db() as db: row=db.execute('SELECT * FROM sessions WHERE id=?',(session,)).fetchone()
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
        return {'session_id':row[0],'task_id':row[1],'turns':json.loads(row[2]),'versions':versions,'pending_request':bool(row[4]),'status':status}
    def define(self,session,contract,origin='user'):
        contract=normalize_contract(contract)
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
        prompt={'instruction':'Extract the actual user task, not the act of defining an interface. Preserve all explicit goals and constraints across turns. Ask only for ambiguity that changes the task. Never ask for architecture, optimizer, precision, latency constraints or dataset version unless the user makes them relevant; select reasonable defaults and record assumptions. Budget is an execution prerequisite, not a reason to ask the user to restate the task. Return the contract object directly, never wrap it in contract or issues. Use the language of the user for explanations and questions. Ask at most five critical questions per turn, record secondary choices as explicit assumptions rather than repeatedly asking. Return JSON contract ONLY with goal, inputs, output_schema, acceptance, budget, assumptions, open_questions, example_input, example_output. Do not invent thresholds or budget, do not weaken previous requirements; put missing facts in open_questions. Inputs are named fields: type image/image_list/video/text, required boolean. image_list requires min_items,max_items,semantics=joint. video requires processing:{sampling,temporal,audio}. Output schema subset: type,properties,required,items,description,enum,additionalProperties,minimum,maximum,minItems,maxItems. Acceptance:{metric,threshold,direction=maximize/minimize,evaluation_protocol}. budget: numeric resource limits. example_input:{sample_id,inputs:{field:{type,uri or items:[{uri}] or value}}}. Joint multi-image is one sample, batch is multiple samples. Never imply training is implemented or performed.', 'turns':[t for t in turns if t['role']=='user'],'previous_contract':normalize_contract(versions[-1]['contract']) if versions else None}
        prompt['change_policy']='Preserve established goal wording, input/output interface, acceptance values and budget exactly unless the user explicitly requests a change. Put implementation choices in assumptions. Do not paraphrase unchanged goal/protocol descriptions. Structural changes are reviewed separately before execution.'
        prompt['format_rules']='output_schema MUST have type=object and nonempty properties; place detection lists inside a detections property, never at the root. assumptions and open_questions MUST be lists of strings, never dictionaries. Video processing sampling, temporal, audio MUST each be nonempty strings; use audio="ignore" for no audio, never false. Missing budget is null, never invented. Examples must satisfy the exact interface. Batch means multiple samples, not image_list. Do not ask for batch size limits, model confidence filters, optimizer or architectural choices unless explicitly constrained by the user; record implementation defaults in assumptions. The inputs section describes INFERENCE-time per-sample inputs only. Training/validation/held-out datasets, annotation files, budgets, weights and evaluation protocols are training resources, NEVER required inference input fields unless the user explicitly requests them as per-sample inputs. Select conventional box coordinates as an assumption, never ask about JSON field names or coordinate syntax. Ask only unresolved task semantics (such as defect class taxonomy or event matching needed to define a metric), not internal representation choices. Resolve schema formatting internally; never ask the user to write JSON schemas.'
        from .detector import COCO_IDS
        prompt['available_adapter_defaults']={'coco_detection':{'use_only_if_matching_user_task':True,'inputs':{'image':{'type':'image','required':True}},'acceptance_metric':'box_AP','metric_units':'0..100','output':'object with detections array; each item has category_id (integer), bbox (4 numbers, COCO xywh pixels), score (0..1)','category_ids':list(COCO_IDS),'note':'80 COCO categories use sparse IDs in 1..90, NOT contiguous 1..80. These are optional implementation defaults, never override an explicit user interface. No claim of training, quality or other task adapter availability.'}}
        client=OpenAICompatibleClient(dict(config,**({'thinking':'disabled'} if config.get('model')=='deepseek-flash' else {})))
        messages=[{'role':'system','content':'You define a visual Agent task interface from the user conversation. Follow these format and scope rules exactly: '+prompt['format_rules']},{'role':'user','content':json.dumps(prompt,ensure_ascii=False)}]
        responses=[];response_ids=[];first_draft=None
        for attempt in range(2):
            response=client.complete(messages,max_tokens=3072)
            response_id=uuid.uuid4().hex
            with self.db() as db:
                db.execute('INSERT INTO clarification_responses VALUES (?,?,?)',(response_id,session,json.dumps(response,ensure_ascii=False)))
            responses.append(response);response_ids.append(response_id)
            # A bounded correction of a received schema is not a network retry.
            # Missing task facts and resource authorization must never be invented.
            try:
                text=response['content'].strip()
                if text.startswith('```'):text=text.split('\n',1)[1].rsplit('```',1)[0]
                draft=normalize_contract(json.loads(text))
                json.dumps(draft,allow_nan=False)
                if not attempt and isinstance(draft,dict):first_draft=draft
                formatting=[error for error in issues(draft) if error.startswith(('需定义 object','输出接口无效:','需记录 assumptions','需记录 open_questions','示例不符合接口:')) or '需明确视频采样、时序与音频处理' in error]
            except (ValueError,TypeError,KeyError,AttributeError):break
            if not formatting or attempt:break
            messages.extend([{'role':'assistant','content':response['content']},
                             {'role':'user','content':json.dumps({'instruction':'Correct these interface formatting errors only. Preserve goal, acceptance, budget, explicit input semantics and all user constraints exactly. Do not ask the user about schema fields. Return the complete corrected contract JSON only.','errors':formatting,'format_rules':prompt['format_rules']},ensure_ascii=False)}])
        review=[];proposed=None
        try:
            if not isinstance(response.get('content'),str):raise ValueError('Model response has no contract text')
            text=response['content'].strip()
            if text.startswith('```'):text=text.split('\n',1)[1].rsplit('```',1)[0]
            contract=normalize_contract(json.loads(text))
            if not isinstance(contract,dict):raise ValueError('Model contract must be an object')
            json.dumps(contract,allow_nan=False)
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
            errors=issues(contract)
            if versions:
                from .requirements import changes
                previous=normalize_contract(versions[-1]['contract'])
                review=changes(previous,contract)
                if review:
                    proposed=contract;contract=previous
                    errors=issues(contract)+['待确认需求变更: '+change['path'] for change in review]
        except (ValueError,TypeError,KeyError,AttributeError) as error:
            contract=normalize_contract(versions[-1]['contract']) if versions else first_draft or {}
            errors=issues(contract)+['解析失败: '+type(error).__name__+'；已保留上一版需求']
        with self.db() as db:
            version={'version':len(versions)+1,'origin':'llm_draft','contract':contract,'issues':errors,'usage':response.get('usage',{})}
            version.update(response_ids=response_ids,response_usage=[item.get('usage',{}) for item in responses],format_correction_attempted=len(responses)>1)
            if review:version.update(review_required=review,proposed_contract=proposed)
            versions.append(version)
            turns.append({'role':'assistant','content':json.dumps({'contract':contract,'issues':errors},ensure_ascii=False)})
            db.execute('UPDATE sessions SET turns=?,versions=?,pending=0 WHERE id=?',(json.dumps(turns,ensure_ascii=False),json.dumps(versions,ensure_ascii=False),session))
        return self.show(session)

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
