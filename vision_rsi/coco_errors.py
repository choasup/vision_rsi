"""Diagnostic COCO match counts; these never replace the task acceptance metric."""
import math


def summarize(evaluator,score_threshold=.05):
    if isinstance(score_threshold,bool) or not isinstance(score_threshold,(int,float)) or not math.isfinite(score_threshold) or not 0<=score_threshold<=1:
        raise ValueError('Invalid diagnostic confidence threshold')
    params=evaluator.params
    indices=[index for index,value in enumerate(params.iouThrs) if abs(float(value)-.5)<1e-9]
    if len(indices)!=1:raise ValueError('COCO default IoU=0.5 match evidence required')
    iou_index=indices[0];area_index=params.areaRngLbl.index('all');maximum=params.maxDets.index(100)
    keys=('true_positives','false_positives','false_negatives','ground_truth')
    counts_by_category={cid:{key:0 for key in keys} for cid in params.catIds}
    # COCO stores K x area x image entries; visit each once rather than once per category.
    for row in evaluator.evalImgs:
        if row is None or row['aRng']!=params.areaRng[area_index]:continue
        counts=counts_by_category[row['category_id']]
        scores=dict(zip(row['dtIds'],row['dtScores']))
        for score,matched,ignored in zip(row['dtScores'],row['dtMatches'][iou_index],row['dtIgnore'][iou_index]):
            if ignored or score<score_threshold:continue
            counts['true_positives' if matched else 'false_positives']+=1
        for matched,ignored in zip(row['gtMatches'][iou_index],row['gtIgnore']):
            if ignored:continue
            counts['ground_truth']+=1
            if not matched or scores.get(matched,0)<score_threshold:counts['false_negatives']+=1
    categories=[]
    for index,cid in enumerate(params.catIds):
        precision=evaluator.eval['precision'][:,:,index,area_index,maximum]
        valid=precision[precision>=0]
        categories.append({'category_id':int(cid),'box_AP':float(valid.mean())*100 if valid.size else None,**counts_by_category[cid]})
    totals={key:sum(row[key] for row in categories) for key in ('true_positives','false_positives','false_negatives','ground_truth')}
    return {'protocol':'COCOeval/bbox/category_AP_and_matches/v1','iou_threshold':.5,'score_threshold':score_threshold,
            'max_detections_per_image_per_category':100,'area':'all','categories':categories,'totals':totals,
            'note':'Counts use IoU0.5 and diagnostic confidence cutoff; AP uses official IoU0.50:0.95 defaults. '
                   'Unmatched predictions do not establish confusion/background/localization cause. Crowd/ignored GT excluded. '
                   'No model-quality or RSI improvement claim; original acceptance is unchanged.'}


def brief(report):
    """Validate diagnostic shape and bound the observations sent to research tools."""
    if report.get('protocol')!='COCOeval/bbox/category_AP_and_matches/v1' or report.get('iou_threshold')!=.5 or report.get('area')!='all' or report.get('max_detections_per_image_per_category')!=100:
        raise ValueError('Unsupported error-analysis protocol')
    score=report.get('score_threshold')
    if isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score) or not 0<=score<=1:raise ValueError('Invalid diagnostic cutoff')
    categories=report.get('categories')
    if not isinstance(categories,list) or not 1<=len(categories)<=80:raise ValueError('Invalid diagnostic category coverage')
    keys=('true_positives','false_positives','false_negatives','ground_truth');seen=set()
    for row in categories:
        cid=row.get('category_id')
        if isinstance(cid,bool) or not isinstance(cid,int) or cid<=0 or cid in seen:raise ValueError('Invalid diagnostic category ID')
        seen.add(cid)
        ap=row.get('box_AP')
        if ap is not None and (isinstance(ap,bool) or not isinstance(ap,(int,float)) or not math.isfinite(ap) or not 0<=ap<=100):raise ValueError('Invalid category AP')
        if any(isinstance(row.get(key),bool) or not isinstance(row.get(key),int) or row[key]<0 for key in keys):raise ValueError('Invalid diagnostic counts')
        if row['true_positives']+row['false_negatives']!=row['ground_truth']:raise ValueError('Diagnostic GT accounting mismatch')
    totals={key:sum(row[key] for row in categories) for key in keys}
    declared=report.get('totals')
    if not isinstance(declared,dict) or set(declared)!=set(keys) or any(isinstance(declared[key],bool) or not isinstance(declared[key],int) for key in keys):raise ValueError('Invalid diagnostic total types')
    if report.get('totals')!=totals:raise ValueError('Diagnostic totals differ from category counts')
    weak=sorted((row for row in categories if row['ground_truth'] and row['box_AP'] is not None),key=lambda row:(row['box_AP'],row['category_id']))[:10]
    false_positives=sorted((row for row in categories if row['false_positives']),key=lambda row:(-row['false_positives'],row['category_id']))[:10]
    return {'protocol':report['protocol'],'iou_threshold':.5,'score_threshold':score,'totals':totals,
            'weakest_annotated_categories':weak,'observed_category_count':len(categories),
            'highest_false_positive_categories':false_positives,
            'interpretation':'Diagnostic matches only; errors do not prove a causal explanation. Fixture/subset limitations remain.'}
