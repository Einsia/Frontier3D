"""Publish only hash-verified submitted previews and reported generation usage."""
from pathlib import Path
from PIL import Image
from tools.publish_l3_suite_scores import read,sha,published_asset

def populate_generation(task,result,assets,downloads):
    model=result["model"];slug=model.removeprefix("gpt-6-")
    run=next(r for r in task["generation_runs"] if r["model"]==model)
    trial=Path(result["source"]["trial"]);record=read(trial/"trial.json")
    if record.get("model")!=model:raise ValueError("Generation metadata model mismatch")
    run.update(seconds=record.get("elapsed_seconds"),finished_unix=record.get("finished_unix"))
    for name,field in [("generation-usage.json","usage_url"),("submission-manifest.json","manifest_url")]:
        source=trial/name
        if source.exists():
            key=task["key"]+"-"+slug+"-"+name
            downloads[key]=published_asset(source);run[field]="/downloads/"+key
            if name=="generation-usage.json":run["usage"]=read(source)
    manifest=trial/"submission-manifest.json"
    previews=record.get("completion_evidence",{}).get("scene_previews",[])
    images=[]
    if manifest.exists() and previews:
        workspace=trial/"workspace";project=workspace/"project";hashes=set()
        for name in previews:
            path=workspace/name
            if path.resolve().is_relative_to(workspace.resolve()) and path.is_file():hashes.add(sha(path))
        for name,expected in sorted(read(manifest).items(),key=lambda row:("overview" not in row[0].lower(),row[0])):
            source=project/name
            if expected not in hashes or source.suffix.lower() not in {".png",".jpg",".jpeg"}:continue
            if not source.resolve().is_relative_to(project.resolve()) or sha(source)!=expected:
                raise ValueError("Submitted preview integrity failure")
            key=task["key"]+"-"+slug+"-"+expected[:20];assets[key]=published_asset(source)
            with Image.open(source) as image:width,height=image.size
            images.append({"url":"/media/"+key,"label":source.stem.replace("_"," "),
                "width":width,"height":height,"source":str(source),"source_sha256":expected,"kind":"generated"})
    if images:run["images"]=images
    elif not run.get("images"):
        legacy=next((x for x in task.get("generation_results",[]) if x.get("model")==model),{})
        run["images"]=legacy.get("images",[])
        for image in run["images"]:
            resource=assets.get(image.get("url","").removeprefix("/media/"))
            if resource and ("width" not in image or "height" not in image):
                with Image.open(resource["path"]) as im:image.update(width=im.width,height=im.height)
    if result.get("status")=="measured" and result.get("source",{}).get("source_sha256"):
        run.setdefault("submitted_images",run.get("images",[]))
        run["images"]=independent_images(task["key"],result,assets)
        run["image_source"]="independent_verifier"
    row=next(r for r in task["model_results"] if r["model_id"]==model);row["usage"]=generation_accounting(run.get("usage",{}),model,run.get("seconds"))
    if task.get("result",{}).get("model_id")==model:
        task["result"]["usage"]=row["usage"]



def independent_images(task_key, result, assets):
    """Bind public previews to the exact scored submission and retained verifier renders."""
    from tools.publish_l3_suite_scores import ROOT
    model=result["model"];slug=model.removeprefix("gpt-6-")
    folder=ROOT/"data/l3/evaluations"/("suite-"+slug+"-v1")/task_key
    expected=result["source"]["source_sha256"]
    if task_key=="l3-g01":
        report=read(folder/("report.json" if slug=="astra" else "algorithms/report.json"))
        visual=report["visual"]
        if report["source_sha256"]!=expected or visual["source_sha256"]!=expected:
            raise ValueError("Scored preview source mismatch")
        rows=[(Path(name),Path(name).stem,checksum) for name,checksum in visual["original_images"].items()
              if "/episodes/views/" in name or name.endswith("/episodes/reference/reference_rgb.png")]
    else:
        source=read(folder/"source.json")
        if source["source_sha256"]!=expected or source["trial"]!=result["source"]["trial"]:
            raise ValueError("Scored preview source mismatch")
        if source["manifest_sha256"]!=sha(Path(source["trial"])/"submission-manifest.json"):
            raise ValueError("Scored submission manifest changed")
        meta=read(folder/"views-metadata.json")
        rows=[(folder/"workspace/episodes/views"/(name+".png"),m["label"],None)
              for name,m in meta.items() if m["kind"]=="view"]
    images=[]
    for path,label,expected_image in rows:
        actual=sha(path)
        if expected_image and actual!=expected_image:raise ValueError("Verifier image changed")
        key=task_key+"-"+slug+"-verified-"+actual[:20]
        assets[key]=published_asset(path)
        with Image.open(path) as im:width,height=im.size
        images.append({"url":"/media/"+key,"label":label,"width":width,"height":height,
                       "source":str(path),"source_sha256":actual,"submission_sha256":expected,
                       "kind":"independent_render"})
    if not images:raise ValueError("No independent scene views for "+task_key+"/"+model)
    return images

def score_csv(existing, tasks):
    """Merge complete L3 scores into the download while preserving other levels."""
    import csv,io
    reader=csv.DictReader(io.StringIO(existing))
    fields=reader.fieldnames
    if not fields or not {'batch_id','task_uid','source_task_id','metric','model','status','score_100'}.issubset(fields):
        raise ValueError("Unknown catalogue score CSV schema")
    rows=[r for r in reader if not r['source_task_id'].startswith('L3/')]
    for task in tasks:
        if task.get('level')!=3:continue
        for result in task.get('evaluation_results',[]):
            model=result.get('model_id',result.get('model'))
            if result.get('status')!='measured':continue
            if result.get('status')!='measured' or result.get('score_100') is None:continue
            rows.append({'batch_id':task['batch_id'],'task_uid':task['batch_id']+'/'+task['id'],
                         'source_task_id':task['id'],'metric':result.get('protocol','l3-algorithm-v1'),
                         'model':model,'status':'scored','score_100':str(result['score_100']),
                         'native_audit_status':''})
    buf=io.StringIO();writer=csv.DictWriter(buf,fieldnames=fields,lineterminator='\n')
    writer.writeheader();writer.writerows(rows);return buf.getvalue()

def generation_accounting(record, model, seconds):
    """Adapt recorded gateway totals to the shared role/model display schema."""
    if not record or 'reported_tokens' not in record:return {}
    calls=record.get('requests_started')
    missing=record.get('requests_without_usage')
    usage_calls=max(0,calls-missing) if isinstance(calls,int) and isinstance(missing,int) else None
    generation={'calls':calls,'usage_calls':usage_calls,'priced_calls':0,
        'seconds':record.get('request_elapsed_seconds_sum'),
        'duration_calls':record.get('requests_finished'),
        'tokens':dict(record['reported_tokens']),
        'usage_complete':missing==0 if missing is not None else False,
        'cost_lower_usd':None,'cost_upper_usd':None}
    return {'workflow_seconds':seconds,'generation':generation,'summary':generation,
        'by_role_model':{'generation':[{'model':model,'value':generation}]},
        'calls':[],'scope':'Recorded generation API usage; absent requests and judge usage are not included.',
        'pricing_version':'未配置'}
