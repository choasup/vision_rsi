"""Read locally collected task-bound training evidence without executing jobs."""
import json
from pathlib import Path
import re

from .runner import digest
from .training_runs import TrainingRuns


def arguments(value):
    if not isinstance(value,dict) or set(value)!={'run_id','expected_record_sha256'}:
        raise ValueError('read_training_run requires exactly run_id and expected_record_sha256')
    if not isinstance(value['run_id'],str) or not re.fullmatch('train-[0-9a-f]{32}',value['run_id']):
        raise ValueError('Invalid Training run ID')
    if not isinstance(value['expected_record_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',value['expected_record_sha256']):
        raise ValueError('Invalid expected training record SHA256')
    return value


def read_json(path,limit):
    with Path(path).open('rb') as stream:raw=stream.read(limit+1)
    if len(raw)>limit:raise ValueError('Collected training evidence exceeds byte limit')
    return json.loads(raw.decode('utf-8-sig'))


def inspect(binding,run_id,contract,expected_record_sha256=None):
    if not isinstance(run_id,str) or not re.fullmatch('train-[0-9a-f]{32}',run_id):raise ValueError('Invalid Training run ID')
    store=TrainingRuns(binding['run_store'],read_only=True)
    try:record=store.get(run_id)
    finally:store.close()
    if record['session_id']!=binding['session_id']:raise ValueError('Training run belongs to another task session')
    checksum=digest(record)
    if expected_record_sha256 is not None:
        arguments({'run_id':run_id,'expected_record_sha256':expected_record_sha256})
        if checksum!=expected_record_sha256:raise ValueError('Training record changed since readiness snapshot; refresh before planning')
    plan=read_json(record['details']['plan_path'],1024*1024)
    if digest(plan)!=record['plan_id']:raise ValueError('Frozen Training plan changed')
    if plan['session_id']!=binding['session_id'] or digest(plan['contract'])!=digest(contract):
        raise ValueError('Training plan does not match frozen research task')
    report={'run_id':run_id,'record_sha256':checksum,'plan_id':record['plan_id'],'recorded_status':record['status'],
            'reserved_gpu_hours':record['reserved_gpu_hours'],'actual_gpu_hours':record['actual_gpu_hours'],
            'receipt_available':False,'receipt_review':None,'quality_verified':False,
            'read_only':True,'remote_called':False,'training_performed':False,
            'scope':'Local recorded evidence only; no live process check, external authenticity verification, capability registration or RSI claim.'}
    if record['details'].get('receipt_path'):
        path=Path(record['details']['receipt_path']).resolve()
        artifacts=(Path(binding['run_store'])/'artifacts'/run_id).resolve()
        if not path.is_relative_to(artifacts) or path.name!='receipt.json':
            raise ValueError('Receipt is outside the collected run artifacts')
        receipt=read_json(path,16*1024*1024)
        if path.parent.parent!=artifacts or path.parent.name!=digest(receipt):
            raise ValueError('Collected receipt identity changed')
        if receipt['run_id']!=run_id:raise ValueError('Training receipt belongs to another run')
        report.update(receipt_available=True,receipt_sha256=digest(receipt))
        from .acceptance import review
        try:
            verdict=review(plan,receipt)
            report['receipt_review']={key:verdict[key] for key in ('status','passed','box_AP','threshold','reasons','error_summary')}
        except (ValueError,KeyError,TypeError) as error:
            report['receipt_review']={'status':'rejected','passed':False,'error_type':type(error).__name__}
    if len(json.dumps(report,ensure_ascii=False))>80000:raise ValueError('Training observation exceeds ledger bound')
    return report
