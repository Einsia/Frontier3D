import base64
import io
import json
from pathlib import Path
import urllib.error

import pytest

from src.agent_judge import responses_runtime as runner
from src.agent_judge.runtime import archive_sessions
from src.run_usage import parse_events, with_archived_usage


class Wire(io.BytesIO):
    status = 200


def wire(response):
    event = {'type': 'response.completed', 'response': response}
    return Wire(('data: ' + json.dumps(event) + '\n\n').encode())


def response(identity, output, incoming=20, outgoing=3):
    return {'id': identity, 'status': 'completed', 'output': output,
            'usage': {'input_tokens': incoming, 'output_tokens': outgoing,
                      'input_tokens_details': {'cached_tokens': 2, 'cache_write_tokens': 0},
                      'output_tokens_details': {'reasoning_tokens': 0}}}


def final():
    return [{'type': 'message', 'role': 'assistant',
             'content': [{'type': 'output_text', 'text': '{"ok":true}'}]}]


def test_multiple_answers_select_first_valid_message_without_score_selection():
    schema={'type':'object','properties':{'score':{'type':'number'}},
            'required':['score'],'additionalProperties':False}
    def message(text):return {'type':'message','content':[{'type':'output_text','text':text}]}
    output=[message('not JSON'),message('{"score":0.1}'),message('{"score":0.9}')]
    assert runner.first_valid_answer(output,schema)=={'score':0.1}
    with pytest.raises(ValueError,match='no schema-valid'):
        runner.first_valid_answer([message('{"wrong":1}')],schema)
    split={'type':'message','content':[{'type':'output_text','text':'{"score":'},
                                      {'type':'output_text','text':'0.2}'}]}
    assert runner.first_valid_answer([split],schema)=={'score':0.2}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    work, home, attempt = (tmp_path/name for name in ['work', 'home', 'attempt'])
    for path in (work, home, attempt):
        path.mkdir()
    (home/'config.toml').write_text('model_provider="test"\n[model_providers.test]\nbase_url="http://example.invalid/v1"\n')
    (work/'response.schema.json').write_text(json.dumps({'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
                                                      'required': ['ok'], 'additionalProperties': False}))
    (work/'image.webp').write_bytes(b'bound-test-image')
    (home/'blender').mkdir()
    (home/'blender/config.json').write_text('{}')
    calls = []

    class FakeTool:
        def __init__(self, *args):
            pass

        def close(self):
            pass

        def request(self, method, params=None):
            if method == 'tools/list':
                return {'tools': [{'name': 'inspect_scene', 'description': 'fixed inspection',
                                   'inputSchema': {'type': 'object', 'properties': {}}}]}
            calls.append(params)
            return {'content': [{'type': 'text', 'text': '{ "objects": [1, 2] }'},
                                {'type': 'image', 'mimeType': 'image/webp', 'data': base64.b64encode(b'tool-pixels').decode()}]}

    monkeypatch.setattr(runner, 'ToolServer', FakeTool)
    args = dict(work=work, home=home, attempt=attempt, prompt='Frozen rubric.', model='gpt-6-astra',
                effort='medium', timeout=10, images=['image.webp'], env={'OPENAI_API_KEY': 'fake-test-secret'})
    return args, calls


def test_actual_request_rounds_and_tools_preserve_evidence_and_counters(setup, monkeypatch):
    args, calls = setup
    function = {'type': 'function_call', 'name': 'judge_blender__inspect_scene', 'call_id': 'c1', 'arguments': '{}'}
    replies = iter([response('r1', [function]), response('r2', final(), incoming=30)])
    sent = []

    def send(req, **kwargs):
        assert req.headers['Authorization'] == 'Bearer fake-test-secret'
        sent.append(json.loads(req.data))
        return wire(next(replies))

    monkeypatch.setattr(runner.urllib.request, 'urlopen', send)
    result = runner.invoke_responses(**args)
    assert result['returncode'] == 0 and result['http_attempts'] == 2
    assert calls == [{'name': 'inspect_scene', 'arguments': {}}]
    assert sent[0]['reasoning'] == {'effort': 'medium'}
    assert 'instructions' not in sent[0]
    assert sent[1]['input'][-1]['call_id'] == 'c1'
    output = sent[1]['input'][-1]['output']
    assert json.loads(output[0]['text']) == {'objects': [1, 2]}
    assert base64.b64decode(output[1]['image_url'].split(',')[1]) == b'tool-pixels'
    assert parse_events(result['stdout'])['usage']['total_tokens'] == 56
    assert json.loads((args['work']/'response.json').read_text()) == {'ok': True}
    assert all('fake-test-secret' not in p.read_text() for p in args['attempt'].rglob('*.json*'))


def test_explicit_instructions_persist_across_tool_rounds_without_changing_rubric(setup, monkeypatch):
    args, calls = setup
    function = {'type': 'function_call', 'name': 'judge_blender__inspect_scene',
                'call_id': 'c1', 'arguments': '{}'}
    replies = iter([response('r1', [function]), response('r2', final())])
    sent = []

    def send(req, **kwargs):
        payload = json.loads(req.data)
        sent.append(payload)
        result = next(replies)
        result['instructions'] = payload['instructions']
        return wire(result)

    monkeypatch.setattr(runner.urllib.request, 'urlopen', send)
    result = runner.invoke_responses(**args, system_instructions=runner.JUDGE_INSTRUCTIONS)
    assert result['returncode'] == 0 and len(calls) == 1
    assert len(sent) == 2
    for payload in sent:
        assert payload['instructions'] == runner.JUDGE_INSTRUCTIONS
        assert payload['input'][1]['content'][0]['text'] == args['prompt']
        assert payload['model'] == 'gpt-6-astra' and payload['reasoning'] == {'effort': 'medium'}
    rows = json.loads((args['attempt']/'api_requests.json').read_text())
    assert all(row['explicit_instructions_match'] is True for row in rows)


@pytest.mark.parametrize('echo', [None, 'Unexpected upstream default instructions'])
def test_explicit_instruction_override_rejects_score_but_retains_billed_usage(setup, monkeypatch, echo):
    args, calls = setup
    reply = response('r1', final())
    reply['instructions'] = echo
    monkeypatch.setattr(runner.urllib.request, 'urlopen', lambda *a, **k: wire(reply))
    result = runner.invoke_responses(**args, system_instructions=runner.JUDGE_INSTRUCTIONS)
    assert result['returncode'] == 1 and 'changed explicit judge instructions' in result['stderr']
    assert not (args['work']/'response.json').exists()
    assert result['complete_http_usage'] is True
    assert parse_events(result['stdout'])['usage']['total_tokens'] == 23
    rows = json.loads((args['attempt']/'api_requests.json').read_text())
    assert rows[0]['explicit_instructions_match'] is False
    assert rows[0]['usage']['total_tokens'] == 23


def test_retried_http_failure_keeps_unknown_cost_scope_after_success(setup, monkeypatch):
    args, _ = setup
    count = 0

    def send(req, **kwargs):
        nonlocal count
        count += 1
        if count == 1:
            raise urllib.error.HTTPError(req.full_url, 524, 'timeout', {}, None)
        return wire(response('r2', final()))

    monkeypatch.setattr(runner.urllib.request, 'urlopen', send)
    result = runner.invoke_responses(**args)
    assert result['returncode'] == 0 and result['complete_http_usage'] is False
    assert parse_events(result['stdout'])['usage'] is None
    archive_sessions(args['home'], args['attempt'], ['fake-test-secret'])
    observed = with_archived_usage(args['attempt'], parse_events(result['stdout']), expected_model='gpt-6-astra')
    assert observed['usage_coverage'] == 'partial' and observed['usage']['total_tokens'] == 23
    requests = json.loads((args['attempt']/'api_requests.json').read_text())
    assert requests[0]['status'] == 'transport_failure' and requests[0]['usage'] is None
    assert requests[1]['response_id'] == 'r2'


def test_unavailable_tools_cannot_execute_code(setup, monkeypatch):
    args, calls = setup
    output = [{'type': 'function_call', 'name': 'shell', 'call_id': 'bad', 'arguments': '{"cmd":"touch unsafe"}'}]
    monkeypatch.setattr(runner.urllib.request, 'urlopen', lambda *a, **k: wire(response('r1', output)))
    result = runner.invoke_responses(**args)
    assert result['returncode'] == 1 and 'unavailable tool' in result['stderr']
    assert not calls and not (args['work']/'response.json').exists()
    assert parse_events(result['stdout'])['usage']['total_tokens'] == 23


def test_transport_retry_budget_is_bounded_and_has_no_zero_usage(setup, monkeypatch):
    args, calls = setup

    def fail(req, **kwargs):
        raise urllib.error.HTTPError(req.full_url, 524, 'timeout', {}, None)

    monkeypatch.setattr(runner.urllib.request, 'urlopen', fail)
    result = runner.invoke_responses(**args)
    assert result['returncode'] == 1 and result['http_attempts'] == 2
    assert parse_events(result['stdout'])['usage'] is None and not calls
    assert all(r['usage'] is None for r in json.loads((args['attempt']/'api_requests.json').read_text()))


def test_stream_disconnect_does_not_fabricate_final_response():
    with pytest.raises(ConnectionError):
        runner.stream_response(Wire(b'data: {"type":"response.created"}\n\n'), lambda event: None)


def test_cache_only_miss_never_sends_http(setup, monkeypatch, tmp_path):
    args, _ = setup
    def forbidden(*args, **kwargs):
        pytest.fail('Cache-only execution must never call the provider')
    monkeypatch.setattr(runner.urllib.request, 'urlopen', forbidden)
    result = runner.invoke_responses(**args, max_rounds=1,
        response_cache=str(tmp_path/'cache'), response_cache_only=True)
    assert result['returncode'] == 1 and result['http_attempts'] == 0
    assert 'HTTP disabled' in result['stderr']
    assert json.loads((args['attempt']/'api_requests.json').read_text()) == []


def test_cache_only_requires_cache(setup, monkeypatch):
    args, _ = setup
    def forbidden(*args, **kwargs):
        pytest.fail('Invalid cache-only settings must never call the provider')
    monkeypatch.setattr(runner.urllib.request, 'urlopen', forbidden)
    result = runner.invoke_responses(**args, response_cache_only=True)
    assert result['returncode'] == 1 and result['http_attempts'] == 0
    assert 'requires a response cache' in result['stderr']


def test_single_round_visual_has_no_tools_and_preserves_original_images(setup, monkeypatch):
    args, calls = setup
    (args['home']/'blender/config.json').unlink()
    sent=[]
    def send(req, **kwargs):
        sent.append(json.loads(req.data))
        return wire(response('visual',final()))
    monkeypatch.setattr(runner.urllib.request,'urlopen',send)
    result=runner.invoke_responses(**args,max_rounds=1,request_attempts=1,max_output_tokens=8000)
    assert result['returncode']==0 and result['http_attempts']==1 and not calls
    assert sent[0]['tools']==[] and sent[0]['tool_choice']=='none'
    assert sent[0]['max_output_tokens']==8000
    image=sent[0]['input'][1]['content'][1]
    assert base64.b64decode(image['image_url'].split(',')[1])==b'bound-test-image'


def test_preload_native_keeps_every_page_without_model_discovery_round(setup,monkeypatch):
    args,_=setup
    native=args['home']/'native-measurements';native.mkdir();(native/'config.json').write_text('{}')
    (args['work']/'judge_spec.json').write_text('{"requirements":[{"id":"r1"}]}')
    pages=[];sent=[]
    class Server:
        def __init__(self,script,*rest):self.native='native_measurements' in str(script)
        def close(self):pass
        def request(self,method,params=None):
            if method=='tools/list':return {'tools':[{'name':'list_native_geometry' if self.native else 'inspect_scene','description':'fixed','inputSchema':{'type':'object'}}]}
            offset=params['arguments']['offset'];pages.append(offset)
            return {'content':[{'type':'text','text':json.dumps({'objects':[offset], 'next_offset':100 if offset==0 else None})}]}
    monkeypatch.setattr(runner,'ToolServer',Server)
    def send(req,**kwargs):
        sent.append(json.loads(req.data));return wire(response('native',final()))
    monkeypatch.setattr(runner.urllib.request,'urlopen',send)
    result=runner.invoke_responses(**args,preload_native=True)
    assert result['returncode']==0 and result['http_attempts']==1 and pages==[0,100]
    content=sent[0]['input'][1]['content']
    assert [json.loads(b['text'])['objects'] for b in content[-2:]]==[[0],[100]]


@pytest.mark.parametrize('provider_code',['server_error','upstream_error','rate_limit_exceeded'])
def test_sse_overload_retries_same_request_and_retains_unknown_usage(setup,monkeypatch,provider_code):
    args,_=setup
    sent=[]
    def send(req,**kwargs):
        sent.append(req.data)
        if len(sent)==1:return wire({'id':'failed1','status':'failed','output':[], 'usage':None,
                                     'error':{'code':provider_code,'type':'service_unavailable_error'}})
        return wire(response('r2',final()))
    monkeypatch.setattr(runner.urllib.request,'urlopen',send)
    result=runner.invoke_responses(**args,request_attempts=2)
    assert result['returncode']==0 and len(sent)==2 and sent[0]==sent[1]
    assert not result['complete_http_usage']
    rows=json.loads((args['attempt']/'api_requests.json').read_text())
    assert rows[0]['status']=='provider_failure' and rows[0]['response_id']=='failed1'
    assert rows[0]['usage'] is None


def test_schema_exposes_only_produced_diagnostic_images(tmp_path):
    schema={'properties':{'file':{'enum':['candidate/main.png','candidate/judge_generated/001.json','candidate/judge_generated/001.png']}}}
    (tmp_path/'response.schema.json').write_text(json.dumps(schema))
    folder=tmp_path/'candidate/judge_generated';folder.mkdir(parents=True)
    (folder/'001.json').write_text('{}')
    result=runner.available_response_schema(tmp_path)
    assert result['properties']['file']['enum']==['candidate/main.png','candidate/judge_generated/001.json']
    assert json.loads((tmp_path/'response.schema.json').read_text())==schema


def test_native_without_diagnostic_render_retains_empty_bound_ledger(tmp_path):
    from src.agent_judge.blender_tools import Broker,sha
    worker=tmp_path/'worker.py';worker.write_text('# fixed worker')
    private=tmp_path/'private';workspace=tmp_path/'workspace';workspace.mkdir()
    broker=Broker({'private':str(private),'workspace':str(workspace),'worker':str(worker),'scenes':{'candidate/scene.blend':'bound-scene-hash'}})
    ledger=json.loads(broker.ledger_path.read_text())
    assert ledger=={'calls':[],'sha256':{},'sources':{'candidate/scene.blend':'bound-scene-hash'},'worker_sha256':sha(worker)}


def test_identical_detail_requests_reuse_first_valid_without_double_billing(setup,monkeypatch):
    from src.agent_judge import response_cache
    args,_=setup;cache=args['attempt'].parent/'cache';sent=[];validated=[]
    monkeypatch.setattr(response_cache,'validate_answer',lambda w,h,a:validated.append(w))
    def send(req,**kwargs):
        sent.append(req.data);return wire(response('r'+str(len(sent)),final()))
    monkeypatch.setattr(runner.urllib.request,'urlopen',send)
    first=runner.invoke_responses(**args,max_rounds=1,response_cache=cache)
    second_attempt=args['attempt'].parent/'second';second_attempt.mkdir()
    second=runner.invoke_responses(**{**args,'attempt':second_attempt},max_rounds=1,response_cache=cache)
    assert first['returncode']==second['returncode']==0 and len(sent)==1 and len(validated)==2
    assert second['http_attempts']==0 and second['http_seconds']==0
    assert second['reused_response']['response_id']=='r1'
    assert parse_events(second['stdout'])['usage']['total_tokens']==0
    assert json.loads((second_attempt/'api_requests.json').read_text())==[]
    (args['work']/'image.webp').write_bytes(b'different-visible-evidence')
    third_attempt=args['attempt'].parent/'third';third_attempt.mkdir()
    third=runner.invoke_responses(**{**args,'attempt':third_attempt},max_rounds=1,response_cache=cache)
    assert third['http_attempts']==1 and len(sent)==2 and third['reused_response'] is None


def test_failed_semantic_validation_is_never_cached(setup,monkeypatch):
    from src.agent_judge import response_cache
    args,_=setup;cache=args['attempt'].parent/'cache'
    def invalid(*a):raise ValueError('Invalid bbox')
    monkeypatch.setattr(response_cache,'validate_answer',invalid)
    monkeypatch.setattr(runner.urllib.request,'urlopen',lambda *a,**k:wire(response('bad',final())))
    result=runner.invoke_responses(**args,max_rounds=1,response_cache=cache)
    assert result['returncode']==1 and 'Invalid bbox' in result['stderr']
    assert not list(cache.glob('*.json'))
    assert parse_events(result['stdout'])['usage']['total_tokens']==23


def test_concurrent_identical_requests_make_one_paid_call(setup,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from src.agent_judge import response_cache
    import shutil
    import time
    args,_=setup;base=args['attempt'].parent;cache=base/'cache';sent=[];validated=[]
    monkeypatch.setattr(response_cache,'validate_answer',lambda w,h,a:validated.append(w))
    def send(req,**kwargs):
        sent.append(req.data);time.sleep(.05);return wire(response('single',final()))
    monkeypatch.setattr(runner.urllib.request,'urlopen',send)
    def invoke(n):
        work=base/f'work-{n}';home=base/f'home-{n}';attempt=base/f'attempt-{n}'
        shutil.copytree(args['work'],work);shutil.copytree(args['home'],home);attempt.mkdir()
        return runner.invoke_responses(**{**args,'work':work,'home':home,'attempt':attempt},
                                       max_rounds=1,response_cache=cache)
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(invoke,range(4)))
    assert all(r['returncode']==0 for r in results)
    assert len(sent)==1 and len(validated)==4
    assert sum(r['http_attempts'] for r in results)==1
    assert sum(parse_events(r['stdout'])['usage']['total_tokens'] for r in results)==23


def test_preloaded_scene_catalogues_preserve_all_pages_and_scenes(setup, monkeypatch):
    args, _ = setup
    (args['home']/'blender/config.json').write_text(json.dumps({'scenes': {
        'candidate/scene.blend': 'candidate-hash', 'reference/scene.blend': 'reference-hash'}}))
    pages, sent = [], []
    class Server:
        def __init__(self, *rest): pass
        def close(self): pass
        def request(self, method, params=None):
            if method == 'tools/list':
                return {'tools': [{'name': 'inspect_scene', 'description': 'fixed', 'inputSchema': {'type': 'object'}}]}
            a = params['arguments'];pages.append((a['scene'], a['offset']))
            return {'content': [{'type': 'text', 'text': json.dumps({
                'evidence': ['candidate/judge_generated/001.json'], 'facts': {
                    'objects': [a['scene'], a['offset']], 'next_offset': 200 if a['offset'] == 0 else None}})}]}
    monkeypatch.setattr(runner, 'ToolServer', Server)
    def send(req, **kwargs):
        sent.append(json.loads(req.data));return wire(response('preloaded', final()))
    monkeypatch.setattr(runner.urllib.request, 'urlopen', send)
    result = runner.invoke_responses(**args, preload_scenes=True)
    assert result['returncode'] == 0 and result['http_attempts'] == 1
    assert pages == [('candidate/scene.blend', 0), ('candidate/scene.blend', 200),
                     ('reference/scene.blend', 0), ('reference/scene.blend', 200)]
    content = sent[0]['input'][1]['content']
    assert [json.loads(b['text'])['facts']['objects'] for b in content[-4:]] == [[s, n] for s, n in pages]


def test_single_round_prepares_every_native_role_before_the_only_request(setup, monkeypatch):
    args, _ = setup
    scenes = ['candidate/scene.blend', 'reference/scene.blend']
    (args['home']/'blender/config.json').write_text(json.dumps({'scenes': dict.fromkeys(scenes, 'hash')}))
    rendered, sent = [], []
    class Server:
        def __init__(self, *rest): pass
        def close(self): pass
        def request(self, method, params=None):
            if method == 'tools/list':
                return {'tools': [{'name': 'render_view', 'description': 'fixed',
                                   'inputSchema': {'type': 'object'}}]}
            rendered.append(params['arguments']['scene'])
            return {'content': [{'type': 'text', 'text': json.dumps({'evidence': rendered[-1]})}]}
    monkeypatch.setattr(runner, 'ToolServer', Server)
    def send(req, **kwargs):
        assert rendered == scenes
        sent.append(json.loads(req.data))
        return wire(response('one-native-request', final()))
    monkeypatch.setattr(runner.urllib.request, 'urlopen', send)
    result = runner.invoke_responses(**args, max_rounds=1, request_attempts=1,
                                     preload_render_roles=True)
    assert result['returncode'] == 0 and len(sent) == result['http_attempts'] == 1
    assert sent[0]['tools'] == [] and sent[0]['tool_choice'] == 'none'
    assert result['preparation_seconds'] >= 0 and result['http_seconds'] >= 0


def test_preloaded_diagnostic_views_keep_pixels_and_full_facts_before_request(setup, monkeypatch):
    from src.agent_judge.fact_codec import decode
    args, _ = setup
    calls, sent = [], []
    facts = {'evidence': ['candidate/judge_generated/001.json'], 'facts': {
        'objects': [{'name': f'piece-{i}', 'location': [i, 0, 1], 'vertices': i + 10,
                     'materials': ['material'], 'hidden_render': False} for i in range(100)]}}
    class Server:
        def __init__(self, *rest): pass
        def close(self): pass
        def request(self, method, params=None):
            if method == 'tools/list':
                return {'tools': [{'name': 'render_view', 'description': 'fixed', 'inputSchema': {'type': 'object'}}]}
            calls.append(params)
            return {'content': [{'type': 'text', 'text': json.dumps(facts)},
                                {'type': 'image', 'mimeType': 'image/webp',
                                 'data': base64.b64encode(b'unchanged-pixels').decode()}]}
    monkeypatch.setattr(runner, 'ToolServer', Server)
    def send(req, **kwargs):
        assert len(calls) == 2
        sent.append(json.loads(req.data));return wire(response('preloaded-views', final()))
    monkeypatch.setattr(runner.urllib.request, 'urlopen', send)
    views = [{'scene': 'candidate/scene.blend', 'azimuth': 145},
             {'scene': 'candidate/scene.blend', 'azimuth': -105}]
    result = runner.invoke_responses(**args, preload_views=views, compact_tool_facts=True)
    assert result['returncode'] == 0 and result['http_attempts'] == 1
    assert [call['arguments'] for call in calls] == views
    content = sent[0]['input'][1]['content']
    for offset in (2, 4):
        assert decode(json.loads(content[offset]['text'])['value']) == facts
        assert base64.b64decode(content[offset + 1]['image_url'].split(',')[1]) == b'unchanged-pixels'
