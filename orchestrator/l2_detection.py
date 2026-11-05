"""Evaluator-owned detector invocation, outside the untrusted candidate sandbox."""
import json
import os
from pathlib import Path
import subprocess
import sys

from .tasks import PROJECT, sha256, write_json


def detect_reference_objects(image, annotation, output, timeout=300):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    python=Path(os.environ.get('L2_DETECTOR_PYTHON',PROJECT/'.venv-grounding/bin/python'))
    model=Path(os.environ.get('L2_DETECTOR_MODEL_DIR',PROJECT/'third_party/grounding-dino-tiny'))
    worker=PROJECT/'src/evaluator/l2_reference_detector_worker.py'
    request={'detector':annotation['detector'],'model_directory':str(model.resolve()),
        'images':[{'key':'main','path':str(Path(image).resolve()),'sha256':sha256(image),
                   'queries':[t['query'] for t in annotation['targets']],
                   'context_queries':annotation.get('context_queries',[])}]}
    write_json(output/'request.json',request)
    command=[str(python),str(worker),str(output/'request.json'),str(output/'detections.json')]
    record={'command':command,'request_sha256':sha256(output/'request.json'),'worker_sha256':sha256(worker)}
    try:
        with (output/'stdout.log').open('w') as stdout,(output/'stderr.log').open('w') as stderr:
            process=subprocess.run(command,stdout=stdout,stderr=stderr,timeout=timeout,check=False)
        if process.returncode:raise RuntimeError('Detector process exit '+str(process.returncode))
        values=json.loads((output/'detections.json').read_text())
        if len(values)!=1 or values[0]['key']!='main':raise ValueError('Detector result inventory mismatch')
        result=values[0];record.update(status='measured',result_sha256=sha256(output/'detections.json'))
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as error:
        result={'status':'not_measurable','score':None,'reason':'Independent detector unavailable: '+str(error),
                'affects_validity':False}
        record.update(status='not_measurable',error=str(error))
    write_json(output/'process.json',record)
    return result
