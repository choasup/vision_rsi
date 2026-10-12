"""Host-owned single-label accuracy; explicit units, exact coverage."""
import math


def evaluate(ground_truth,predictions,classes,threshold,unit):
    if unit not in ('fraction','percent'):raise ValueError('Accuracy unit must be fraction or percent')
    if (not isinstance(classes,list) or len(classes)<2 or any(not isinstance(c,str) or not c for c in classes)
            or len(set(classes))!=len(classes)):raise ValueError('Explicit unique class labels required')
    maximum=1 if unit=='fraction' else 100
    if isinstance(threshold,bool) or not isinstance(threshold,(int,float)) or not math.isfinite(threshold) or not 0<=threshold<=maximum:
        raise ValueError('Invalid accuracy threshold')
    def index(rows,prediction):
        if not isinstance(rows,list) or not rows:raise ValueError('Nonempty sample records required')
        result={}
        for row in rows:
            if not isinstance(row,dict):raise ValueError('Invalid record')
            key=row.get('sample_id');label=row.get('label')
            if not isinstance(key,str) or not key or key in result:raise ValueError('Missing or duplicate sample ID')
            if label not in classes:raise ValueError('Unknown class label')
            if prediction:
                confidence=row.get('confidence')
                if isinstance(confidence,bool) or not isinstance(confidence,(int,float)) or not math.isfinite(confidence) or not 0<=confidence<=1:
                    raise ValueError('Invalid confidence')
            result[key]=label
        return result
    truth=index(ground_truth,False);predicted=index(predictions,True)
    if truth.keys()!=predicted.keys():raise ValueError('Prediction coverage must exactly match ground truth')
    correct=sum(predicted[key]==label for key,label in truth.items())
    value=maximum*correct/len(truth)
    return {'metric':'accuracy','unit':unit,'value':value,'correct':correct,'total':len(truth),
            'threshold':threshold,'passed':value>=threshold,'direction':'maximize',
            'scope':'Supplied labeled samples only; no claim of dataset independence or production acceptance'}
