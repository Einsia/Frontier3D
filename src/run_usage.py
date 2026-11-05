"""Read Codex usage without equating missing counters with zero."""
import json
import hashlib
import math
from pathlib import Path
import re


def number(value):
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0 else None


def normalize_usage(raw):
    if not isinstance(raw,dict):return None
    input_details=raw.get('input_tokens_details') or {}
    output_details=raw.get('output_tokens_details') or {}
    if not isinstance(input_details,dict) or not isinstance(output_details,dict):return None
    fields={'input_tokens':raw.get('input_tokens'), 'output_tokens':raw.get('output_tokens'),
        'cached_input_tokens':raw.get('cached_input_tokens',input_details.get('cached_tokens')),
        'cache_write_input_tokens':raw.get('cache_write_input_tokens',input_details.get('cache_write_tokens')),
        'reasoning_output_tokens':raw.get('reasoning_output_tokens',output_details.get('reasoning_tokens'))}
    result={key:number(value) for key,value in fields.items()}
    if result['input_tokens'] is None or result['output_tokens'] is None:return None
    if any(result[k] is not None and result[k]>result['input_tokens'] for k in ['cached_input_tokens','cache_write_input_tokens']):return None
    if sum(result[k] or 0 for k in ['cached_input_tokens','cache_write_input_tokens'])>result['input_tokens']:return None
    if (result['reasoning_output_tokens'] or 0)>result['output_tokens']:return None
    result['total_tokens']=result['input_tokens']+result['output_tokens']
    return result


def parse_events(text,stderr=''):
    sessions=[];turns=[]
    for line in text.splitlines():
        try:event=json.loads(line)
        except (ValueError,TypeError):continue
        if not isinstance(event,dict):continue
        if event.get('type')=='thread.started' and isinstance(event.get('thread_id'),str):sessions.append(event['thread_id'])
        if event.get('type')=='turn.completed':
            value=normalize_usage(event.get('usage'))
            if value is not None:turns.append(value)
    sessions+=re.findall(r'(?m)^session id:\s*([a-zA-Z0-9-]+)\s*$',stderr)
    reported=re.findall(r'(?m)^tokens used\s*\n([\d,]+)\s*$',stderr)
    usage=None
    if turns:
        usage={key:sum(turn[key] for turn in turns) if all(turn[key] is not None for turn in turns) else None for key in turns[0]}
    return {'session_ids':list(dict.fromkeys(sessions)),'usage':usage,
        'turns':turns,'cli_reported_tokens':int(reported[-1].replace(',','')) if reported else None}


def archived_response_usage(directory,*,expected_model=None,expected_sessions=()):
    """Sum completed response counters from a hash-bound private runtime archive.

    This is a partial observation: requests that never returned usage remain unknown.
    Cumulative turn/thread counters are never added to per-response counters.
    """
    directory=Path(directory);manifest_path=directory/'session_archive.json'
    if not manifest_path.exists():return None
    manifest=json.loads(manifest_path.read_text());responses={};sessions=set();models=set();sources=[]
    for item in manifest['files']:
        path=(directory/item['path']).resolve()
        if not path.is_relative_to(directory.resolve()) or path.is_symlink():raise ValueError('Usage archive path escapes attempt')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Usage archive hash changed')
        sources.append(item)
        for line in raw.decode('utf-8').splitlines():
            try:event=json.loads(line)
            except ValueError:continue
            payload=event.get('payload',{})
            if event.get('type')=='session_meta' and payload.get('id'):sessions.add(payload['id'])
            if event.get('type')=='turn_context' and payload.get('model'):models.add(payload['model'])
            if event.get('type')!='token_usage_record':continue
            identity=payload.get('response_id');session=payload.get('session_id') or payload.get('thread_id')
            usage=normalize_usage(payload.get('usage'))
            if not identity or not session or usage is None:raise ValueError('Incomplete runtime response usage record')
            if identity in responses and responses[identity]!=(session,usage):raise ValueError('Conflicting counters for response')
            responses[identity]=(session,usage)
    if not responses:return None
    response_sessions={v[0] for v in responses.values()}
    if not response_sessions<=sessions:raise ValueError('Usage response lacks bound session metadata')
    if expected_sessions and not response_sessions<=set(expected_sessions):raise ValueError('Usage response belongs to another session')
    if expected_model and models!={expected_model}:raise ValueError('Usage archive model mismatch')
    rows=[v[1] for v in responses.values()]
    usage={key:sum(row[key] for row in rows) if all(row[key] is not None for row in rows) else None for key in rows[0]}
    return {'usage':usage,'session_ids':sorted(response_sessions),'usage_coverage':'partial',
        'usage_provenance':{'source':'archived_response_records','archive':'session_archive.json',
            'archive_sha256':hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            'files':sources,'response_ids':sorted(responses),'recorded_responses':len(responses),
            'scope':'Completed responses observed before interruption; unreturned request usage remains unknown.'}}


def with_archived_usage(directory,observed,*,expected_model=None):
    if observed.get('usage') is not None:
        return {**observed,'usage_coverage':'complete','usage_provenance':{'source':'cli_turn_completed'}}
    partial=archived_response_usage(directory,expected_model=expected_model,expected_sessions=observed.get('session_ids',[]))
    return {**observed,**partial} if partial else {**observed,'usage_coverage':'unknown'}


def estimate_cost(usage,model,pricing):
    """Standard-tier reference estimate; ranges expose missing cache/context detail."""
    rate=pricing['models'].get(model)
    if not usage or not rate:return None
    incoming=usage['input_tokens'];outgoing=usage['output_tokens'];cached=usage['cached_input_tokens'];writes=usage['cache_write_input_tokens']
    if cached is None:
        low_input=incoming*rate['cached_input'];high_input=incoming*rate['cache_write']
    else:
        remaining=incoming-cached
        low_input=cached*rate['cached_input']+(remaining-(writes or 0))*rate['input']+(writes or 0)*rate['cache_write']
        high_input=low_input if writes is not None else cached*rate['cached_input']+remaining*rate['cache_write']
    # Codex turn usage aggregates API requests. A large total is not proof of a
    # long-context request; give a range instead of applying a false exact rate.
    context_unknown=incoming>rate.get('long_context_threshold',272000)
    lower=(low_input+outgoing*rate['output'])/1e6
    upper=(high_input*(2 if context_unknown else 1)+outgoing*rate['output']*(1.5 if context_unknown else 1))/1e6
    return {'lower_usd':lower,'upper_usd':upper,'basis':'standard_api_reference_estimate',
        'pricing_version':pricing['version'],'context_ambiguous':context_unknown,
        'cache_ambiguous':cached is None or writes is None,'actual_charge':False}
