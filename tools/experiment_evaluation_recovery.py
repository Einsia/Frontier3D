"""Bounded recovery of unsuccessful judge caches; preserve CPU and accepted calls."""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

from datetime import datetime, timezone

import fcntl

import json

import os

from pathlib import Path

import time

RETRYABLE_JUDGE_STATES = {'not_measurable', 'failed', 'technical_failure',
                          'needs_recovery', 'interrupted', 'budget_exhausted'}

def read(path):
    return json.loads(path.read_text())

def atomic(path, value):
    temporary = path.with_name(path.name+'.'+str(os.getpid())+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    temporary.replace(path)

def recover_judges(stage, job_folder, label, indexes):
    """Allow one recovery per task/stage, excluding scored and model task outcomes.

    A judge budget is a failed measurement attempt, not a candidate's execution
    budget. Only explicit final judge failures qualify. Unfinished/live judge
    directories and native task budget failures are left for separate recovery.
    """
    stage, job_folder = Path(stage), Path(job_folder)
    candidates = [stage/'judge', stage/'raw'/'judge']
    candidates += sorted(stage.glob('variants/*/judge'))
    candidates += sorted(stage.glob('variants/*/*/judge'))
    candidates = list(dict.fromkeys(candidates))
    failed = []
    for directory in candidates:
        marker = directory/'run.json'
        if not marker.is_file():
            continue
        try:
            judgment = read(marker)
        except (OSError, ValueError):
            continue
        if judgment.get('status') in RETRYABLE_JUDGE_STATES:
            failed.append(directory)
    if not failed:
        return None
    journal = job_folder/'evaluation-recovery.json'
    saved = read(journal) if journal.is_file() else {'stages': {}}
    if saved['stages'].get(label, {}).get('attempts', 0) >= 1:
        return None
    archive = job_folder/'evaluation-recovery'/str(time.time_ns())/label
    archive.mkdir(parents=True, exist_ok=False)
    moves = []
    sources = [*failed, *(stage/name for name in indexes)]
    for source in sources:
        if not source.exists():
            continue
        target = archive/source.relative_to(stage)
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
        moves.append({'source': str(source), 'archive': str(target)})
    record = {'attempts': 1, 'updated_utc': datetime.now(timezone.utc).isoformat(),
              'reason': 'Retry failed judge stage once; preserve CPU and accepted judge caches',
              'moves': moves}
    atomic(archive/'manifest.json', record)
    saved['stages'][label] = record
    atomic(journal, saved)
    return record

def recover_historical(root, model, task_id, job_folder):
    """Clear negative aggregate indexes only when their judge stage failed."""
    root = Path(root)
    name = Path(task_id).name
    base = root/'legacy_baseline'/model/'cases'/name
    detail = root/'legacy_detail'/model/name
    changes = []
    if (base/'report.json').is_file() and read(base/'report.json').get('S_core') is None:
        value = recover_judges(base, job_folder, 'historical-baseline',
                               ['report.json', 'raw/result.json', 'raw/report.json'])
        if value:
            changes.append(value)
    if (detail/'detail.json').is_file() and read(detail/'detail.json').get('status') != 'measured':
        value = recover_judges(detail, job_folder, 'historical-detail', ['detail.json'])
        if value:
            changes.append(value)
    return changes

def recover_partial_seeds(source, job_folder):
    """Archive interrupted seed directories without retrying completed attempts."""
    source, job_folder = Path(source), Path(job_folder)
    stage = source/'legacy_execution'
    path = stage/'variants.json'
    manifest = read(path) if path.is_file() else {}
    journal = job_folder/'evaluation-recovery.json'
    saved = read(journal) if journal.is_file() else {'stages': {}}
    changes = []
    for name in ('seed-0', 'seed-1', 'seed-2'):
        directory = stage/name
        label = 'addition-interrupted-execution-'+name
        if (not directory.is_dir() or (directory/'attempts.json').exists()
                or name in manifest.get('variants', {})
                or manifest.get('executions', {}).get(name, {}).get('status') == 'success'
                or saved['stages'].get(label, {}).get('attempts', 0) >= 1):
            continue
        target = job_folder/'evaluation-recovery'/str(time.time_ns())/label/name
        target.parent.mkdir(parents=True, exist_ok=False)
        directory.rename(target)
        record = {'attempts': 1, 'updated_utc': datetime.now(timezone.utc).isoformat(),
                  'reason': 'Interrupted seed directory has no completed attempt; retain evidence and retry once',
                  'moves': [{'source': str(directory), 'archive': str(target)}]}
        atomic(target.parent/'manifest.json', record)
        saved['stages'][label] = record
        atomic(journal, saved)
        changes.append(record)
    return changes

def recover_partial_image_renders(source, job_folder):
    """Recover an interrupted image check while preserving completed receipts."""
    source, job_folder = Path(source), Path(job_folder)
    stage = source/'legacy_image_integrity'
    if (stage/'report.json').exists():
        return []
    state = read(stage/'status.json') if (stage/'status.json').is_file() else {}
    journal = job_folder/'evaluation-recovery.json'
    saved = read(journal) if journal.is_file() else {'stages': {}}
    changes = []
    for seed in ('primary', 'seed-0', 'seed-1', 'seed-2'):
        directory = stage/seed/'renders'
        label = 'addition-interrupted-image-renders-'+seed
        if (not directory.is_dir() or directory.is_symlink()
                or (stage/seed/'receipt.json').exists()
                or seed in state.get('finished_variants', [])
                or saved['stages'].get(label, {}).get('attempts', 0) >= 1):
            continue
        target = job_folder/'evaluation-recovery'/str(time.time_ns())/label/'renders'
        target.parent.mkdir(parents=True, exist_ok=False)
        directory.rename(target)
        record = {'attempts': 1, 'updated_utc': datetime.now(timezone.utc).isoformat(),
                  'reason': 'Interrupted authored-view render has no receipt or completion marker; preserve and retry once',
                  'moves': [{'source': str(directory), 'archive': str(target)}]}
        atomic(target.parent/'manifest.json', record)
        saved['stages'][label] = record
        atomic(journal, saved)
        changes.append(record)
    return changes

def recover_partial_inspections(source, job_folder, identity):
    """Retain interrupted L2 inspections once; never reopen completed facts."""
    source, job_folder = Path(source), Path(job_folder)
    stage = source/'legacy_reproducibility'
    if not stage.is_dir() or stage.is_symlink() or (stage/'report.json').exists():
        return []
    identity = {key: identity[key] for key in ('model', 'effort', 'task_id')}
    with (stage/'case.lock').open('a') as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = read(stage/'status.json') if (stage/'status.json').is_file() else {}
        journal = job_folder/'evaluation-recovery.json'
        saved = read(journal) if journal.is_file() else {'stages': {}}
        changes = []
        for seed in ('primary', 'seed-0', 'seed-1', 'seed-2'):
            parent = stage/seed
            directory = parent/'inspection'
            label = 'addition-interrupted-reproducibility-inspection-'+seed
            if (not directory.is_dir() or directory.is_symlink() or parent.is_symlink()
                    or (parent/'receipt.json').exists() or (parent/'facts.json').exists()
                    or seed in state.get('inspected', [])
                    or saved['stages'].get(label, {}).get('attempts', 0) >= 1):
                continue
            target = job_folder/'evaluation-recovery'/str(time.time_ns())/label/'inspection'
            target.parent.mkdir(parents=True, exist_ok=False, mode=0o777)
            # These are the only new directories introduced by this recovery.
            for path in (target.parent, target.parent.parent, target.parent.parent.parent):
                path.chmod(0o777)
            directory.rename(target)
            record = {'attempts': 1, 'identity': identity, 'seed': seed,
                      'updated_utc': datetime.now(timezone.utc).isoformat(),
                      'reason': 'Interrupted native inspection has no receipt, facts, report or inspected marker; retain evidence and retry once',
                      'moves': [{'source': str(directory), 'archive': str(target)}]}
            atomic(target.parent/'manifest.json', record)
            saved['stages'][label] = record
            atomic(journal, saved)
            changes.append(record)
        return changes
