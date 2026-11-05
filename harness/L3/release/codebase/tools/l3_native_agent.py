"""Native authoring CLIs in the isolated L3 workspace. No provider secrets."""
import argparse,json,os,subprocess,sys,time,fcntl
from pathlib import Path
BASE='http://127.0.0.1:8765'


CLOSEOUT_CONTROL = Path('/opt/l3-public/user-closeout.json')

def authorized_closeout(a):
    if not CLOSEOUT_CONTROL.exists():
        return None
    control = json.loads(CLOSEOUT_CONTROL.read_text())
    if control.get('schema_version') != 1 or control.get('approved_by_user') is not True:
        raise ValueError('Closeout instruction requires recorded user approval')
    if any(control.get(k) != getattr(a, k) for k in ('harness', 'model', 'effort')):
        raise ValueError('Closeout identity does not match the native invocation')
    if a.harness != 'claude':
        raise ValueError('Persisted closeout is supported only for ClaudeCode')
    import uuid
    uuid.UUID(control['session_id'])
    if not isinstance(control.get('instruction'), str) or not control['instruction'].strip():
        raise ValueError('Closeout instruction is empty')
    if not control.get('operation_id'):
        raise ValueError('Closeout operation provenance is required')
    return control


def command_for(a,prompt):
    policy_file=__import__('pathlib').Path(__file__).with_name('model-harness-contract.json')
    if not policy_file.exists():policy_file=__import__('pathlib').Path(__file__).resolve().parents[5]/'configs/release/model-harness-contract.json'
    policy=json.loads(policy_file.read_text())
    declared=next((r for r in policy['models'] if r['model'].casefold()==a.model.casefold()),None)
    names={'codex':'codex','claude-code':'claude','kimi-codecli':'kimi','deepseek-harness':'dsh','zcode':'zcode','gemini-cli':'gemini'}
    if declared and a.harness!=names[declared['harness_id']]:
        raise ValueError(f'{a.model} generation requires '+('Claude Code' if declared['harness_id']=='claude-code' else declared['harness'])+' for L1/L2/L3')
    if declared and a.effort!=declared['effort']:raise ValueError('Model contract requires effort '+declared['effort'])
    home=Path('/workspace/.native')/a.harness;home.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,CODEX_API_KEY='local-bridge-no-secret')
    control=authorized_closeout(a)
    if control is not None:prompt=control['instruction']
    refs=a.image or []
    if a.harness=='codex':
        cmd=['codex','exec','--dangerously-bypass-approvals-and-sandbox','--skip-git-repo-check','--json','--model',a.model,'--output-last-message','/workspace/agent-final.txt']
        for ref in refs:cmd+=['--image',ref]
        return cmd+['-'],prompt,env
    if a.harness=='claude':
        env.update(ANTHROPIC_API_KEY='local-bridge-no-secret',ANTHROPIC_BASE_URL=BASE,CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',CLAUDE_CONFIG_DIR=str(home))
        if a.model.casefold().startswith(('doubao','qwen')):
            env.update(ANTHROPIC_CUSTOM_MODEL_OPTION=a.model,
                       ANTHROPIC_CUSTOM_MODEL_OPTION_SUPPORTED_CAPABILITIES='effort,max_effort,thinking,adaptive_thinking')
        prompt+='\nRead the supplied reference images with the Read tool: '+', '.join(refs) if refs else ''
        cmd=['/opt/cli/node_modules/.bin/claude','-p','--bare','--model',a.model,'--effort',a.effort,'--output-format','stream-json','--verbose','--setting-sources','','--tools','Read,Glob,Grep,Bash,Write,Edit','--allowedTools','Read,Glob,Grep,Bash,Write,Edit','--dangerously-skip-permissions']
        if control is not None:cmd+=['--resume',control['session_id']]
        return cmd,prompt,env
    if a.harness=='dsh':
        patch=[{'id':'agent-default-model','config':{'provider':'deepseek-official','model':a.model}}, {'id':'llm-deepseek','config':{'baseURL':BASE+'/v1','apiKeyEnv':'DEEPSEEK_API_KEY','reasoningEffort':a.effort,'maxTokens':65536,'models':[{'id':a.model,'inputModalities':['text','image']}]}}, *[{'id':x,'disabled':True} for x in ['session-title-llm','tool-subagent','tool-subagent-fork']]]
        file=home/'benchmark.json';file.write_text(json.dumps(patch));env.update(DSH_HOME=str(home),DEEPSEEK_API_KEY='local-bridge-no-secret')
        if refs:prompt+='\nInspect supplied reference images with your file tools: '+', '.join(refs)
        return ['/opt/cli/node_modules/.bin/dsh','--profile','headless','--patch',str(file),'--json','-'],prompt,env
    if a.harness=='kimi':
        (home/'config.toml').write_text(f'default_model = "{a.model}"\ndefault_permission_mode = "yolo"\n[providers.gw]\ntype = "openai"\nbase_url = "{BASE}/v1"\napi_key_env = "CODEX_API_KEY"\n[models."{a.model}"]\nprovider = "gw"\nmodel = "{a.model}"\nmax_context_size = 262144\ncapabilities = ["image_in", "thinking"]\n')
        env.update(KIMI_CODE_HOME=str(home),KIMI_MODEL_THINKING_EFFORT=a.effort)
        if refs:prompt+='\nInspect supplied reference images with ReadMediaFile: '+', '.join(refs)
        return ['node','/opt/cli/node_modules/.bin/kimi','-p',prompt,'--output-format','stream-json','-m',a.model],None,env
    if a.harness=='zcode':
        provider={'schemaVersion':1,'config':{'providerConfigRules':{'providerRules':[{'providerId':'gw','providerName':'Gateway','enabled':True,'config':{'group':'standard-personal','access':{'type':'api-key','apiKey':'local-bridge-no-secret'},'api':{'type':'openai-chat-completions','baseUrl':BASE+'/v1','headers':{}},'personalModelIds':[a.model],'modelOrder':[a.model],'visibility':'visible'}}]},'modelConfigRules':{'providerModelRules':[{'providerId':'gw','modelId':a.model,'config':{'enabled':True,'properties':{'contextWindow':200000,'supportsToolCall':True,'inputFormat':{'supportsText':True,'supportsImage':True}},'optionSpecs':{'maxOutputTokens':{'max':65536,'map':'{"max_tokens": maxOutputTokens}'},'reasoningLevel':{'values':['disabled','low','medium','high','xhigh','max'],'map':'reasoningLevel == "disabled" ? {} : {"reasoning_effort": reasoningLevel}'}}}}],'manualProviderModelRules':[]},'defaultModelSelection':{'providerId':'gw','modelId':a.model,'options':{'reasoningLevel':a.effort}}}}
        path=home/'provider_config.json';path.write_text(json.dumps(provider))
        env.update(ZCODE_DATA_BASE_DIR=str(home),ZCODE_CLI_SETTINGS_FILE=str(home/'setting.json'),ZCODE_PERSONAL_PROVIDER_CONFIG_FILE=str(path),ZCODE_CLI_CREDENTIALS_FILE=str(home/'credentials.json'),ZCODE_SESSION_DB_PATH=str(home/'db.sqlite'),ZCODE_DISABLE_UPDATE_CHECK='1',ZCODE_MODEL_RETRY_MAX_RETRIES='3')
        cmd=['node','/opt/cli/node_modules/.bin/zcode','--json','--model','gw/'+a.model,'--effort',a.effort,'--mode','yolo','--cwd','/workspace/project']
        for ref in refs:cmd+=['--attach',ref]
        return cmd+['-p',prompt],None,env
    if a.harness=='gemini':
        env.update(HOME=str(home),GEMINI_API_KEY='local-bridge-no-secret',GOOGLE_GEMINI_BASE_URL=BASE)
        settings=home/'.gemini';settings.mkdir(exist_ok=True)
        (settings/'settings.json').write_text(json.dumps({'security':{'auth':{'selectedType':'gemini-api-key'}},'model':{'name':a.model},'telemetry':{'enabled':False}}))
        if refs:prompt+='\nRead the supplied reference images: '+', '.join(refs)
        return ['/opt/cli/node_modules/.bin/gemini','--model',a.model,'--approval-mode','yolo','--output-format','stream-json','-p',prompt],None,env
    raise ValueError(a.harness)

def run(a):
    lock=Path('/workspace/.native-agent.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        print('A native authoring process already owns this workspace.',flush=True)
        return 75
    prompt=Path(a.prompt).read_text();cmd,stdin,env=command_for(a,prompt)
    control=authorized_closeout(a)
    intervention=({'operation_id':control['operation_id'],'session_id':control['session_id'],'instruction_sha256':__import__('hashlib').sha256(control['instruction'].encode()).hexdigest()} if control else None)
    if intervention:print(json.dumps({'type':'user_intervention.resumed',**intervention}),flush=True)
    started=time.time();terminal=False;final=None;raw=[]
    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=sys.stderr,text=True,env=env,cwd='/workspace/project',bufsize=1)
    if stdin is not None:proc.stdin.write(stdin);proc.stdin.close()
    for line in proc.stdout:
        print(line,end='',flush=True);raw.append(line)
        try:v=json.loads(line)
        except ValueError:continue
        if not isinstance(v,dict):continue
        if a.harness=='codex' and v.get('type')=='turn.completed':terminal=True
        if a.harness=='claude' and v.get('type')=='result':terminal=not v.get('is_error',False);final=v.get('result')
        if a.harness=='dsh' and v.get('type')=='final':terminal=True;final=v.get('text')
        if a.harness=='kimi' and v.get('role')=='assistant' and not v.get('tool_calls'):
            val=v.get('content');final=''.join(x.get('text','') for x in val if isinstance(x,dict)) if isinstance(val,list) else val
        if a.harness=='zcode' and isinstance(v.get('response'),str):terminal=True;final=v['response']
        if a.harness=='gemini' and v.get('type')=='message' and v.get('role')=='assistant':final=(final or '')+v.get('content','')
        if a.harness=='gemini' and v.get('type')=='result':terminal=v.get('status')=='success'
    rc=proc.wait()
    if a.harness=='zcode' and not terminal:
        try:v=json.loads(''.join(raw));final=v.get('response');terminal=isinstance(final,str)
        except ValueError:pass
    if a.harness=='kimi':terminal=bool(final)
    success=rc==0 and terminal
    if success and final:Path('/workspace/agent-final.txt').write_text(final)
    result={'harness':a.harness,'model':a.model,'effort':a.effort,'return_code':rc,'completed':success,'elapsed_seconds':time.time()-started,'finished_unix':time.time()}
    if intervention:result['user_intervention']=intervention
    Path(a.result).write_text(json.dumps(result,indent=2));print(json.dumps({'type':'native_runner.finished',**result}),flush=True)
    return 0 if success else 1

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--harness',required=True);p.add_argument('--model',required=True);p.add_argument('--effort',required=True);p.add_argument('--prompt',required=True);p.add_argument('--result',required=True);p.add_argument('--image',action='append');sys.exit(run(p.parse_args()))
