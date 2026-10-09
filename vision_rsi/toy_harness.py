"""Small executable detection harness for CLI integration validation, not COCO."""
import json
import math
import sys


def predict(image, threshold):
    if not isinstance(image, list) or not image or not isinstance(image[0], list) or not image[0]:
        raise ValueError('image must be a nonempty rectangular intensity matrix')
    width = len(image[0])
    if any(not isinstance(row, list) or len(row) != width for row in image):
        raise ValueError('image must be rectangular')
    points = []
    for y, row in enumerate(image):
        for x, value in enumerate(row):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 255:
                raise ValueError('intensity must be finite and in [0,255]')
            if value >= threshold: points.append((x,y))
    if not points: return []
    x0,y0=min(x for x,y in points),min(y for x,y in points)
    x1,y1=max(x for x,y in points)+1,max(y for x,y in points)+1
    return [{'bbox':[x0,y0,x1-x0,y1-y0], 'category_id':1, 'score':1.0}]


def iou(prediction, target):
    if not prediction: return 0.0
    a=prediction[0]['bbox']; b=target
    if not isinstance(b,list) or len(b)!=4 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in b) or b[2]<=0 or b[3]<=0:
        raise ValueError('target bbox must have four finite values and positive dimensions')
    intersection=max(0,min(a[0]+a[2],b[0]+b[2])-max(a[0],b[0]))*max(0,min(a[1]+a[3],b[1]+b[3])-max(a[1],b[1]))
    return intersection/(a[2]*a[3]+b[2]*b[3]-intersection)


if __name__ == '__main__':
    model=json.load(open(sys.argv[1],encoding='utf-8'))
    sample=json.load(open(sys.argv[2],encoding='utf-8'))
    print(json.dumps({'predictions':predict(sample['image'],model['threshold'])}))
