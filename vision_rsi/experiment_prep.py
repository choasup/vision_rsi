"""Local, read-only environment inspection after collecting a four-field brief."""
import os
from pathlib import Path
import platform
import shutil
import sys

from .contracts import brief_questions, interface_issues
from .runner import atomic_json, digest


def prepare(session, root):
    if session.get('pending_request') or not session.get('versions'):
        raise ValueError('需求尚未完成。')
    latest=session['versions'][-1]
    if latest.get('review_required'):
        raise ValueError('请先确认当前草案。')
    contract=latest['contract']
    blockers=brief_questions(contract)+interface_issues(contract)
    if blockers:
        raise ValueError('；'.join(blockers))
    source=contract['data_source']
    environment={'host':platform.node(),'platform':platform.system(),
                 'python':sys.version.split()[0], 'working_directory':str(Path.cwd()),
                 'nvidia_smi_available':shutil.which('nvidia-smi') is not None,
                 'gpu_verified':False}
    data={'source':source,'inspected_on':environment['host'],'dataset_validated':False}
    if source['kind']=='local':
        location=Path(source['location']).expanduser().resolve()
        data.update(resolved_path=str(location),exists=location.exists(),readable=os.access(location,os.R_OK))
        next_step='检查数据标签与切分，再确认实验预算和训练后端。' if data['exists'] and data['readable'] else '修正当前机器不可访问的数据路径；无需重新描述输入输出。'
    else:
        data.update(download_performed=False,download_allowed=source.get('download_allowed') is True)
        next_step='选择具体公开数据集并检查下载条件；下载尚未执行。'
    report={'status':'experiment_prepared','session_id':session['session_id'],
            'contract_sha256':digest(contract),'inputs':contract['inputs'],
            'output_schema':contract['output_schema'],'validation_goal':contract['acceptance'],
            'environment':environment,'data':data,'assumptions':contract.get('assumptions',[]),
            'next_step':next_step,'training_performed':False,'quality_verified':False,
            'remaining_steps':['校验真实数据与标签','固定训练和评测切分','核查训练后端与依赖','确认资源上限后执行实验']}
    if not isinstance(session['session_id'],str) or len(session['session_id'])!=32 or any(c not in '0123456789abcdef' for c in session['session_id']):
        raise ValueError('Invalid session ID')
    path=Path(root).resolve()/session['session_id']/digest(contract)/'experiment-preparation.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    atomic_json(path,report)
    return dict(report,report_path=str(path))


def summary(report):
    data=report['data']
    lines=['四项需求已齐全，已进入实验准备。',
           '已检查当前机器：'+report['environment']['host']+'；Python '+report['environment']['python']]
    if data['source']['kind']=='local':
        lines.append('数据路径：'+data['resolved_path']+('（存在且可读）' if data['exists'] and data['readable'] else '（不存在或不可读）'))
    else:lines.append('公开数据来源：'+data['source']['location']+'；尚未下载。')
    if report['validation_goal'].get('mode')=='baseline':lines.append('验证方式：先测基线，不预设达标数值。')
    lines.extend(['下一步：'+report['next_step'],'准备记录：'+report['report_path'],
                  '尚未启动训练；GPU、数据内容和训练后端仍需核查。'])
    return '\n'.join(lines)
