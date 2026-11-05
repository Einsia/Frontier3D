"""First-valid response reuse for byte-identical single-round detail requests."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import time

from .protocol import digest, read_json, score, write_json


def response_digest(response):
    return hashlib.sha256(json.dumps(response,sort_keys=True,ensure_ascii=False,
                                     separators=(',',':')).encode()).hexdigest()


@contextmanager
def locked_entry(directory, request_sha256, deadline):
    import fcntl
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    with (directory/(request_sha256+'.lock')).open('a') as lease:
        while True:
            try:
                fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic()>=deadline:raise TimeoutError('Identical-request cache wait exceeded deadline')
                time.sleep(.05)
        yield directory/(request_sha256+'.json')


def read_entry(path, request_sha256):
    if not path.exists():return None
    entry=read_json(path)
    if (entry.get('version')!='first-valid-detail-response-v1' or
        entry.get('request_sha256')!=request_sha256 or
        entry.get('response_sha256')!=response_digest(entry['response']) or
        entry['response'].get('status')!='completed'):
        raise ValueError('Invalid or modified detail response cache')
    return entry


def validate_answer(work, home, answer):
    """Every reuse must pass its own artifact and native-render provenance checks."""
    from .generated import verified_evidence
    from .task_continuous import PROTOCOL
    spec=read_json(work/'judge_spec.json')
    if spec.get('protocol')!=PROTOCOL:
        raise ValueError('Response reuse is restricted to continuous detail judgments')
    manifest=read_json(work/'manifest.json')
    for relative,expected in manifest['sha256'].items():
        if digest(work/relative)!=expected:raise ValueError('Input changed before response reuse')
    generated=home/'blender/generated' if manifest['mode']=='interactive' else None
    return score(answer,spec,verified_evidence(manifest,generated))


def store_entry(path, request_sha256, response, source_attempt):
    if path.exists():raise ValueError('Never replace the first valid cached response')
    write_json(path,{'version':'first-valid-detail-response-v1','request_sha256':request_sha256,
        'response_sha256':response_digest(response),'response':response,
        'source_attempt':str(Path(source_attempt).resolve())})
