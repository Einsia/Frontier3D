"""Whole-checklist transport; item anchors and aggregation stay independent."""
import copy
from .rubric import CHECKS, validate_verdict

def checklist_schema(item_schema):
    return {'type':'object','properties':{k:copy.deepcopy(item_schema) for k in CHECKS},
            'required':list(CHECKS),'additionalProperties':False}

def validate_checklist(value, names):
    if not isinstance(value,dict):raise ValueError('Checklist must be an object')
    verdicts={};errors={}
    for key in CHECKS:
        item=value.get(key)
        try:
            if not isinstance(item,dict):raise ValueError('Missing item verdict')
            score=item.get('score')
            if score is not None and (type(score) is not int or not 0<=score<=4):raise ValueError('Invalid ordinal grade')
            if not item.get('evidence') or any(n not in names for n in item['evidence']):raise ValueError('Invalid image citation')
            for field in ['confidence','not_judgeable','critical_failures']: 
                if field not in item:raise ValueError('Missing '+field)
            validate_verdict(item)
            verdicts[key]=item
        except (ValueError,KeyError,TypeError) as error:
            verdicts[key]=None;errors[key]=str(error)
    return verdicts,errors
