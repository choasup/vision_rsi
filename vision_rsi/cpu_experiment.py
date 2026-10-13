"""Real CPU digits baseline: split, train, select, export, predict and measure.

A reproducible local experiment, not the general conversational training backend.
Training requires scikit-learn; exported inference uses only the standard library.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

from .runner import atomic_json


def checksum(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def predict(model_path, input_path, output_path):
    output_path=Path(output_path).resolve()
    if output_path.exists() or output_path in (Path(model_path).resolve(),Path(input_path).resolve()):
        raise ValueError('Prediction output must be a new file distinct from model/input')
    model=json.loads(Path(model_path).read_text())
    samples=json.loads(Path(input_path).read_text())
    finite=lambda x:not isinstance(x,bool) and isinstance(x,(int,float)) and math.isfinite(x)
    if not isinstance(model,dict):raise ValueError('Model must be an object')
    classes=model.get('classes');weights=model.get('coefficients');biases=model.get('intercepts')
    if (not isinstance(classes,list) or len(classes)<2 or any(not isinstance(c,str) for c in classes)
            or len(set(classes))!=len(classes) or not isinstance(weights,list) or not isinstance(biases,list)
            or len(weights)!=len(classes) or len(biases)!=len(classes)
            or any(not isinstance(row,list) or len(row)!=64 or not all(map(finite,row)) for row in weights)
            or not all(map(finite,biases))):
        raise ValueError('Invalid linear model dimensions or values')
    if not isinstance(samples,list) or not samples:raise ValueError('Nonempty sample list required')
    rows=[];seen=set()
    for sample in samples:
        if not isinstance(sample,dict):raise ValueError('Sample must be an object')
        key=sample.get('sample_id');pixels=sample.get('pixels')
        if not isinstance(key,str) or not key or key in seen:
            raise ValueError('Unique sample IDs required')
        seen.add(key)
        if not isinstance(pixels,list) or len(pixels)!=64 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or not 0<=x<=16 for x in pixels):
            raise ValueError('Expected 64 finite grayscale values in [0,16]')
        logits=[bias+sum(w*x/16 for w,x in zip(weights,pixels))
                for weights,bias in zip(model['coefficients'],model['intercepts'])]
        probabilities=[math.exp(x-max(logits)) for x in logits]
        total=sum(probabilities);index=max(range(len(probabilities)),key=probabilities.__getitem__)
        rows.append({'sample_id':key,'label':model['classes'][index],'confidence':probabilities[index]/total})
    atomic_json(output_path,rows)
    return rows


def run(output, seed=20261013):
    import numpy as np
    import sklearn
    from sklearn.datasets import load_digits
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split
    from threadpoolctl import threadpool_limits
    from .contracts import Sessions,validate_schema
    from .harness import build

    root=Path(output).resolve()
    root.mkdir(parents=True,exist_ok=False)
    started=time.monotonic()
    data=load_digits();x=data.data;y=data.target
    # No identical input may cross splits, regardless of its label.
    image_hashes=[hashlib.sha256(row.tobytes()).hexdigest() for row in x]
    if len(set(image_hashes))!=len(x):raise ValueError('Duplicate images require grouping before splitting')
    indices=np.arange(len(y))
    train,remaining=train_test_split(indices,test_size=.4,random_state=seed,stratify=y)
    development,test=train_test_split(remaining,test_size=.5,random_state=seed+1,stratify=y[remaining])
    for a,b in ((train,development),(train,test),(development,test)):
        if set(a)&set(b):raise ValueError('Overlapping split IDs')
    ids=lambda values:[int(i) for i in values]
    splits={'seed':seed,'train':ids(train),'development':ids(development),'test':ids(test),
            'dataset_sha256':hashlib.sha256(x.tobytes()+y.tobytes()).hexdigest(),
            'image_sha256':image_hashes,'source':'sklearn.datasets.load_digits (bundled UCI handwritten digits)',
            'download_performed':False,'test_used_for_selection':False}
    atomic_json(root/'splits.json',splits)
    classes=[str(i) for i in range(10)]
    contract={'goal':'Classify an 8x8 grayscale handwritten digit from 0 to 9',
              'inputs':{'image':{'type':'image','required':True}},
              'output_schema':{'type':'object','properties':{'label':{'type':'string','enum':classes},
                               'confidence':{'type':'number','minimum':0,'maximum':1}},'required':['label','confidence']},
              'data_source':{'kind':'local','location':str(root/'splits.json'),'download_allowed':False},
              'acceptance':{'mode':'baseline','metric':'accuracy','threshold':None,'direction':'maximize',
                            'evaluation_protocol':'One held-out test evaluation after C selection on development data'},
              'budget':{'gpu_hours':0},'assumptions':['Pixel intensities 0..16; divide by 16; softmax linear classifier; CPU only'],
              'open_questions':[],
              'example_input':{'sample_id':'example','inputs':{'image':{'type':'image','uri':str(root/'sample.pgm')}}},
              'example_output':{'label':'0','confidence':.5}}
    store=Sessions(root/'sessions');session=store.create('digits-cpu-baseline',contract['goal'])
    session=store.define(session['session_id'],contract)
    interface=build(session,root/'interfaces')
    check=subprocess.run([sys.executable,'-B',str(Path(interface['directory'])/'harness.py'),'check'],capture_output=True,text=True,check=True,timeout=30)
    atomic_json(root/'interface-check.json',json.loads(check.stdout))
    trials=[];best=None
    with threadpool_limits(limits=1):
        for c in (.1,1.,10.):
            tick=time.monotonic()
            model=LogisticRegression(C=c,max_iter=1000,solver='lbfgs')
            model.fit(x[train]/16,y[train])
            if int(model.n_iter_.max())>=1000:raise ValueError('Training did not converge')
            correct=int((model.predict(x[development]/16)==y[development]).sum())
            trial={'C':c,'development_correct':correct,'development_total':len(development),
                   'development_accuracy':correct/len(development),'training_seconds':time.monotonic()-tick,
                   'iterations':ids(model.n_iter_)}
            trials.append(trial)
            print('C='+str(c)+' development accuracy='+str(round(trial['development_accuracy'],4)),flush=True)
            if best is None or correct>best[0]:best=(correct,model,c)
    _,model,c=best
    atomic_json(root/'trials.json',trials)
    atomic_json(root/'model.json',{'kind':'digits_linear_softmax_v1','coefficients':model.coef_.tolist(),
                                 'intercepts':model.intercept_.tolist(),'classes':[str(i) for i in model.classes_],
                                 'input_scale':16,'selected_C':c})
    frozen_model=checksum(root/'model.json')
    # Predictor input contains no labels. Inference runs in a fresh process.
    samples=[{'sample_id':'digits-'+str(i),'pixels':x[i].tolist()} for i in test]
    atomic_json(root/'test-inputs.json',samples)
    atomic_json(root/'test-labels.json',[{'sample_id':'digits-'+str(i),'label':str(y[i])} for i in test])
    command=[sys.executable,'-m','vision_rsi.cpu_experiment','predict','--model',str(root/'model.json'),
             '--input',str(root/'test-inputs.json'),'--output',str(root/'test-predictions.json')]
    subprocess.run(command,cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,check=True,timeout=30)
    predictions=json.loads((root/'test-predictions.json').read_text())
    truth={row['sample_id']:row['label'] for row in json.loads((root/'test-labels.json').read_text())}
    if len(predictions)!=len(truth) or {p['sample_id'] for p in predictions}!=set(truth):raise ValueError('Incomplete prediction coverage')
    confusion=[[0]*10 for _ in range(10)]
    correct=0
    for row in predictions:
        validate_schema(contract['output_schema'],{'label':row['label'],'confidence':row['confidence']})
        target=truth[row['sample_id']];correct+=row['label']==target
        confusion[int(target)][int(row['label'])]+=1
    reference=model.predict(x[test]/16)
    if [row['label'] for row in predictions]!=[str(i) for i in reference]:raise ValueError('Exported inference differs from trained model')
    if checksum(root/'model.json')!=frozen_model:raise ValueError('Model changed during evaluation')
    sample=x[test[0]].reshape(8,8)
    (root/'sample.pgm').write_text('P2\n8 8\n16\n'+'\n'.join(' '.join(str(int(v)) for v in row) for row in sample)+'\n')
    atomic_json(root/'sample-input.json',[samples[0]])
    report={'status':'completed','training_performed':True,'gpu_hours':0,'api_calls':0,
            'dataset':splits['source'],'samples':len(y),'split_sizes':{'train':len(train),'development':len(development),'test':len(test)},
            'selected_C':c,'test_accuracy':correct/len(test),'test_correct':correct,'test_total':len(test),
            'confusion_matrix':confusion,'test_evaluations':1,'test_used_for_selection':False,
            'exported_predictions_match_sklearn':True,'session_id':session['session_id'],'model_sha256':frozen_model,
            'wall_seconds':time.monotonic()-started,'python':sys.version.split()[0],'numpy':np.__version__,'sklearn':sklearn.__version__,
            'sample_prediction':predictions[0],'sample_expected':truth[predictions[0]['sample_id']],
            'user_acceptance_verified':False,'limitations':'Small bundled digits dataset; no cat/dog capability or general conversational training integration.'}
    atomic_json(root/'report.json',report)
    atomic_json(root/'artifacts.json',{p.name:checksum(p) for p in root.iterdir() if p.is_file()})
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['run','predict'])
    parser.add_argument('--output',required=True)
    parser.add_argument('--seed',type=int,default=20261013)
    parser.add_argument('--model');parser.add_argument('--input')
    args=parser.parse_args(argv)
    try:
        if args.action=='run':result=run(args.output,args.seed)
        else:
            if not args.model or not args.input:parser.error('predict requires --model and --input')
            result=predict(args.model,args.input,args.output)
    except (ValueError,OSError,ImportError,subprocess.SubprocessError) as error:
        detail=error.stderr[-2000:] if isinstance(error,subprocess.CalledProcessError) and error.stderr else str(error)
        parser.exit(1,'Experiment failed: '+detail+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
