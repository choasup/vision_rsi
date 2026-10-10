"""Preregistered paired campaigns; observed comparisons never imply adoption."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import time

from .campaign import advance,campaign_binding,lease
from .campaign_audit import audit
from .candidates import git,verify_candidate
from .contracts import Sessions,issues
from .runner import atomic_json,digest,revision
from .training_runs import TrainingRuns

SIGN_RULE={'test':'exact_one_sided_sign_test_above_gain_threshold','alpha':.05,'minimum_non_tied_pairs':5,
           'ties':'exclude exact ties at preregistered gain threshold'}


def resource_comparison(baseline,candidate):
    """Observed deltas, never replace unknown costs with zero or infer fairness."""
    rows={};missing=[]
    for metric,complete in (('settled_gpu_hours','gpu_accounting_settled'),
                            ('observed_action_wall_seconds','action_timing_complete'),
                            ('known_llm_tokens','llm_usage_complete')):
        values={}
        for arm,result in (('baseline',baseline),('candidate',candidate)):
            value=result.get(metric)
            valid=(result.get(complete) is True and not isinstance(value,bool)
                   and isinstance(value,(int,float)) and math.isfinite(value) and value>=0)
            if metric=='known_llm_tokens':valid=valid and isinstance(value,int)
            values[arm]=value if valid else None
            if not valid:missing.append(arm+': '+metric+' missing or incomplete')
        rows[metric]={**values,'candidate_minus_baseline':
                     values['candidate']-values['baseline'] if all(x is not None for x in values.values()) else None}
    for arm,result in (('baseline',baseline),('candidate',candidate)):
        if not isinstance(result.get('llm_cost_scope'),str) or not result['llm_cost_scope']:
            missing.append(arm+': LLM cost scope missing')
    same_scope=(isinstance(baseline.get('llm_cost_scope'),str) and bool(baseline['llm_cost_scope'])
                and baseline.get('llm_cost_scope')==candidate.get('llm_cost_scope'))
    if not same_scope:missing.append('LLM cost scopes differ or are unavailable')
    return {'metrics':rows,'observed_costs_complete':not missing,'missing_evidence':missing,
            'llm_cost_scopes':{arm:result.get('llm_cost_scope') for arm,result in (('baseline',baseline),('candidate',candidate))},
            'equal_resource_budgets_verified':False,'rsi_efficiency_verified':False,
            'scope':'Observed GPU, action wall-time and experiment-proposal tokens only; not total CPU, billing or whole-project costs.'}


def paired_sign_evidence(gains,threshold,rule):
    if rule!=SIGN_RULE:raise ValueError('Unsupported preregistered statistical rule')
    if isinstance(threshold,bool) or not isinstance(threshold,(int,float)) or not math.isfinite(threshold):raise ValueError('Invalid statistical gain threshold')
    if not isinstance(gains,list) or not 1<=len(gains)<=100 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in gains):
        raise ValueError('Statistical comparison requires complete finite paired gains')
    positive=sum(x>threshold for x in gains);negative=sum(x<threshold for x in gains)
    count=positive+negative
    probability=sum(math.comb(count,k) for k in range(positive,count+1))/2**count if count else None
    sufficient=count>=rule['minimum_non_tied_pairs']
    return {'evaluated':True,'rule':dict(rule),'gain_threshold':threshold,'positive_pairs':positive,'negative_pairs':negative,
            'tied_pairs':len(gains)-count,'non_tied_pairs':count,'p_value':probability,'sufficient_non_tied_pairs':sufficient,
            'preregistered_sign_rule_met':bool(sufficient and probability<=rule['alpha']),
            'assumption':'One-sided null: conditional on a non-tie, probability of gain above threshold is at most 0.5; pairs must be independent.',
            'independence_verified':False,'agent_adopted':False}


def sources():
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob('*.py'))}


def create(spec,config,root='runs/paired-studies',sessions='runs/training-sessions',campaigns='runs/campaigns',runs='runs/training-runs'):
    if git(Path.cwd(),'status','--porcelain','--untracked-files=no'):raise ValueError('Commit control source before preregistration')
    if set(spec)!={'candidate','pairs','research_rounds','minimum_mean_ap_gain','heldout_declaration'}:
        raise ValueError('Study requires candidate, pairs, research_rounds, minimum_mean_ap_gain and heldout_declaration')
    policy=dict(spec['candidate']);policy['store']=str(Path(policy['store']).resolve())
    if set(policy)!={'candidate_id','module','store'} or not re.fullmatch('[0-9a-f]{64}',policy['candidate_id']):raise ValueError('Invalid study candidate')
    candidate=verify_candidate(policy['store'],json.loads((Path(policy['store'])/policy['candidate_id']/'candidate.json').read_text(encoding='utf-8')))
    if not isinstance(policy['module'],str) or not re.fullmatch(r'vision_rsi\.(research|strategy_[a-z][a-z0-9_]*)',policy['module']):raise ValueError('Invalid strategy module')
    if policy['module'].replace('.','/')+'.py' not in set(candidate['source_hashes'])|{'vision_rsi/research.py'}:raise ValueError('Strategy module absent from candidate source bundle')
    rounds=spec['research_rounds'];gain=spec['minimum_mean_ap_gain']
    if isinstance(rounds,bool) or not isinstance(rounds,int) or not 0<=rounds<=10:raise ValueError('Invalid research limit')
    if isinstance(gain,bool) or not isinstance(gain,(int,float)) or not math.isfinite(gain) or gain<=0:raise ValueError('Require a positive finite AP improvement threshold')
    if not isinstance(spec['heldout_declaration'],str) or not spec['heldout_declaration'].strip():raise ValueError('Describe independent held-out task selection')
    if not isinstance(spec['pairs'],list) or not 2<=len(spec['pairs'])<=100:raise ValueError('Study requires 2..100 preregistered pairs')
    # Copy only supported service configuration; never persist credentials.
    safe={'remote':{k:config['remote'][k] for k in ('ssh_host','ssh_port','workspace','python','coco_root') if k in config['remote']},
          'llm':{k:config['llm'][k] for k in ('model','base_url','api_key_env','thinking','usage_ledger','usage_call_limit') if k in config['llm']},
          'training':dict(config.get('training',{}))}
    from .controller_budget import configured_limit
    configured_limit(config)
    if 'controller' in config:safe['controller']=dict(config['controller'])
    from .llm_usage import ledger_path,validate_call_limit
    if 'usage_ledger' in safe['llm']:ledger_path(safe['llm']['usage_ledger'])
    if 'usage_call_limit' in safe['llm']:
        validate_call_limit(safe['llm']['usage_call_limit'])
        if 'usage_ledger' not in safe['llm']:raise ValueError('Study API call limit requires an absolute shared usage ledger')
    allowed={'detector','epochs','batch_size_per_gpu','seed','checkpoint_steps','world_size','min_size','max_size','learning_rate','weight_decay','fixture','coco_root','weights','weights_sha256','train_annotations_sha256','val_annotations_sha256','acceptance_threshold','timeout_seconds'}
    if set(safe['training'])-allowed:raise ValueError('Unsupported training configuration in study')
    from .coco_train import validate_recipe
    from .training_plan import DEFAULT_RECIPE
    recipe={**DEFAULT_RECIPE,**safe['training']};recipe.pop('timeout_seconds',None)
    recipe['coco_root']=safe['remote'].get('coco_root') or recipe.get('coco_root','')
    if recipe.get('fixture') is not False:raise ValueError('Real paired study cannot use fixture recipes')
    validate_recipe(recipe,path_flavor='posix')
    store=Sessions(sessions);used=set();pair_contexts=set();pairs=[]
    ledger=TrainingRuns(runs,read_only=True) if (Path(runs)/'training-runs.sqlite3').is_file() else None
    try:
        for pair in spec['pairs']:
            if set(pair)!={'baseline_session','candidate_session','seed'} or isinstance(pair['seed'],bool) or not isinstance(pair['seed'],int):raise ValueError('Each pair needs two session IDs and an integer seed')
            arms={};contracts=[]
            pair_config=json.loads(json.dumps(safe));pair_config['training']['seed']=pair['seed']
            validate_recipe({**recipe,'seed':pair['seed']},path_flavor='posix')
            for arm,key in [('baseline','baseline_session'),('candidate','candidate_session')]:
                sid=pair[key]
                if sid in used:raise ValueError('Every study arm needs a distinct session')
                used.add(sid);session=store.show(sid)
                if session['pending_request'] or not session['versions']:raise ValueError('Task clarification must be settled before study')
                latest=session['versions'][-1];contract=latest['contract']
                if issues(contract) or latest.get('review_required'):raise ValueError('Study task requirements are incomplete')
                budget=(contract.get('budget') or {}).get('gpu_hours')
                if isinstance(budget,bool) or not isinstance(budget,(int,float)) or not math.isfinite(budget) or budget<=0:raise ValueError('Each arm needs an authorized GPU budget')
                if ledger and ledger.list(sid):raise ValueError('Study session already contains Training runs')
                for path in (Path(campaigns)/sid).glob('*/state.json'):
                    if json.loads(path.read_text(encoding='utf-8')).get('history'):raise ValueError('Preregister before campaign execution')
                binding=campaign_binding(session,pair_config,runs,policy if arm=='candidate' else None,rounds)
                arms[arm]={'session_id':sid,'contract_version':latest['version'],'campaign_id':digest(binding),'binding':binding}
                contracts.append(contract)
            if digest(contracts[0])!=digest(contracts[1]):raise ValueError('Paired arms must have identical task requirements and budget')
            context=(digest(contracts[0]),pair['seed'])
            if context in pair_contexts:raise ValueError('Repeated task/seed pair is not independent replication')
            pair_contexts.add(context)
            pairs.append({'seed':pair['seed'],'config':pair_config,**arms})
    finally:
        if ledger:ledger.close()
    identity={'pairs':pairs,'registered_at_unix':time.time(),'candidate_git_revision':candidate['git_revision'],'candidate_source_hashes':candidate['source_hashes'],
              'control_sources':sources(),'git_revision':revision(),'sessions':str(Path(sessions).resolve()),'campaigns':str(Path(campaigns).resolve()),
              'runs':str(Path(runs).resolve()),'minimum_mean_ap_gain':gain,'heldout_declaration':spec['heldout_declaration'],
              'statistical_rule':dict(SIGN_RULE),
              'comparison_rule':'Mean paired best real COCO AP gain at equal authorized GPU budgets; every preregistered arm must settle and pass independent evidence audit.'}
    sid=digest(identity);folder=Path(root)/sid;folder.mkdir(parents=True,exist_ok=True);path=folder/'study.json'
    record={'study_id':sid,'identity':identity,'agent_adopted':False}
    with lease(folder/'study.lock'):
        if path.exists():
            if json.loads(path.read_text(encoding='utf-8'))!=record:raise ValueError('Study manifest changed')
        else:atomic_json(path,record)
    return record


def load(study_id,root):
    if not isinstance(study_id,str) or not re.fullmatch('[0-9a-f]{64}',study_id):raise ValueError('Invalid study ID')
    record=json.loads((Path(root)/study_id/'study.json').read_text(encoding='utf-8'))
    if record['study_id']!=study_id or digest(record['identity'])!=study_id:raise ValueError('Study identity changed')
    return record


def step(study_id,pair_index,arm,root='runs/paired-studies',steps=3):
    record=load(study_id,root);identity=record['identity']
    if sources()!=identity['control_sources'] or revision()!=identity['git_revision']:raise ValueError('Run study from its frozen control source revision')
    verify_study_candidate(identity)
    if arm not in ('baseline','candidate') or isinstance(pair_index,bool) or not isinstance(pair_index,int) or not 0<=pair_index<len(identity['pairs']):raise ValueError('Invalid study arm or pair index')
    pair=identity['pairs'][pair_index];bound=pair[arm]
    session=Sessions(identity['sessions']).show(bound['session_id'])
    if len(session['versions'])!=bound['contract_version']:raise ValueError('Study contract version changed')
    binding=campaign_binding(session,pair['config'],identity['runs'],bound['binding']['policy'],bound['binding']['research_rounds'])
    if binding!=bound['binding']:raise ValueError('Study campaign requirements changed')
    path=Path(identity['campaigns'])/bound['session_id']/bound['campaign_id']/'state.json'
    return advance(session,pair['config'],identity['campaigns'],identity['runs'],steps,binding['policy'],research_rounds=binding['research_rounds'],selected_campaign=bound['campaign_id'] if path.exists() else None)


def verify_study_candidate(identity):
    policy=identity['pairs'][0]['candidate']['binding']['policy']
    record=verify_candidate(policy['store'],json.loads((Path(policy['store'])/policy['candidate_id']/'candidate.json').read_text(encoding='utf-8')))
    if record['git_revision']!=identity['candidate_git_revision'] or record['source_hashes']!=identity['candidate_source_hashes']:
        raise ValueError('Candidate differs from preregistered Git/source identity')


def compare(study_id,root='runs/paired-studies'):
    record=load(study_id,root);identity=record['identity'];pairs=[];missing=[]
    verify_study_candidate(identity)
    for index,pair in enumerate(identity['pairs']):
        results={}
        for arm in ('baseline','candidate'):
            bound=pair[arm]
            try:
                path=Path(identity['campaigns'])/bound['session_id']/bound['campaign_id']/'state.json'
                state_raw=path.read_bytes();state=json.loads(state_raw)
                if state['binding']!=bound['binding']:raise ValueError('Campaign binding differs from preregistration')
                if state.get('paused') or state.get('intent') or state.get('status') not in ('needs_research','awaiting_serving_validation','budget_exhausted','policy_stopped'):
                    raise ValueError('Campaign is not settled for final comparison')
                from .campaign import available
                if available(state):raise ValueError('Preregistered research actions remain')
                for row in state['history']+([state['policy_stop']] if state.get('policy_stop') else []):
                    if row.get('control_sources')!=identity['control_sources'] or row.get('git_revision')!=identity['git_revision']:raise ValueError('Control code changed during study')
                    if row.get('created_at_unix',0)<identity['registered_at_unix']:raise ValueError('Action predates study registration')
                result=audit(bound['session_id'],bound['campaign_id'],identity['campaigns'],identity['runs'])
                if result['campaign_state_sha256']!=hashlib.sha256(state_raw).hexdigest():raise ValueError('Campaign changed during comparison; repeat observation without restarting work')
                if not result['evidence_complete_for_review'] or result['best_verified_real_box_AP'] is None:raise ValueError('Independent campaign evidence incomplete: '+'; '.join(result['missing_evidence']))
                results[arm]=result
            except (ValueError,KeyError,TypeError,OSError) as error:missing.append({'pair':index,'arm':arm,'error':str(error)})
        if len(results)==2:
            setups=[]
            from .training_plan import DEFAULT_RECIPE
            expected={**DEFAULT_RECIPE,**pair['config']['training']};expected.pop('timeout_seconds',None)
            expected['coco_root']=pair['config']['remote'].get('coco_root') or expected.get('coco_root','')
            expected['acceptance_threshold']=pair['baseline']['binding']['contract']['acceptance']['threshold']
            mutable=('learning_rate','weight_decay','epochs','batch_size_per_gpu','min_size','max_size','checkpoint_steps')
            for key in mutable:expected.pop(key,None)
            setup_valid=True
            for result in results.values():
                for measured in result['measurements']:
                    setup=json.loads(json.dumps(measured['training_identity']))
                    for key in mutable:setup['recipe'].pop(key,None)
                    if setup['recipe']!=expected or setup.get('sources')!=identity['control_sources']:setup_valid=False
                    setups.append(setup)
            if not setup_valid or not setups or any(digest(setup)!=digest(setups[0]) for setup in setups):
                missing.append({'pair':index,'error':'Paired runs used different data, weights, seeds, code or runtime'})
            else:pairs.append({'pair':index,'seed':pair['seed'],'ap_gain':results['candidate']['best_verified_real_box_AP']-results['baseline']['best_verified_real_box_AP'],
                               'resource_comparison':resource_comparison(results['baseline'],results['candidate']),'arms':results})
    complete=not missing and len(pairs)==len(identity['pairs']);mean=sum(p['ap_gain'] for p in pairs)/len(pairs) if complete else None
    statistical={'evaluated':False,'preregistered_sign_rule_met':False,
                 'reason':'Incomplete paired evidence' if not complete else 'Legacy study has no preregistered statistical rule'}
    if complete and 'statistical_rule' in identity:
        statistical=paired_sign_evidence([p['ap_gain'] for p in pairs],identity['minimum_mean_ap_gain'],identity['statistical_rule'])
    return {'study_id':study_id,'pairs':pairs,'missing_evidence':missing,'comparison_complete':complete,'mean_paired_ap_gain':mean,
            'preregistered_gain_rule_met':complete and mean>=identity['minimum_mean_ap_gain'],
            'paired_statistical_evidence':statistical,
            'rsi_efficiency_verified':False,'agent_adopted':False,
            'limitation':'Observed preregistered GPU-budget comparison only. Held-out independence is a declaration, not verified provenance; statistical replication and full multi-resource budget review remain required before adoption.'}


def main(argv):
    parser=argparse.ArgumentParser(prog='vision-rsi study');parser.add_argument('action',choices=['create','show','advance','compare'])
    parser.add_argument('--spec');parser.add_argument('--config',default='config.local.json');parser.add_argument('--study-id');parser.add_argument('--store',default='runs/paired-studies')
    parser.add_argument('--sessions',default='runs/training-sessions');parser.add_argument('--campaign-store',default='runs/campaigns');parser.add_argument('--run-store',default='runs/training-runs')
    parser.add_argument('--pair',type=int);parser.add_argument('--arm',choices=['baseline','candidate']);parser.add_argument('--steps',type=int,default=3)
    args=parser.parse_args(argv)
    try:
        if args.action=='create':
            if not args.spec:parser.error('create requires --spec')
            result=create(json.loads(Path(args.spec).read_text(encoding='utf-8-sig')),json.loads(Path(args.config).read_text(encoding='utf-8-sig')),args.store,args.sessions,args.campaign_store,args.run_store)
        elif args.action=='advance':result=step(args.study_id,args.pair,args.arm,args.store,args.steps)
        elif args.action=='compare':result=compare(args.study_id,args.store)
        else:result=load(args.study_id,args.store)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,KeyError,TypeError,OSError,RuntimeError,subprocess.SubprocessError) as error:parser.exit(1,str(error)+'\n')
