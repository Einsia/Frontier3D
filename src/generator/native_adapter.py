"""One native invocation for DSH, Kimi, ZCode or Gemini; parent owns retries."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with os.fdopen(os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600), 'w') as f:
        json.dump(value, f)


def command_for(args, prompt):
    home = args.session / args.harness
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    base = args.base_url.rstrip('/').removesuffix('/v1')
    env = dict(os.environ)
    key = env['CODEX_API_KEY']
    if args.schema:
        prompt += '\nReturn only a complete JSON value matching this schema, without Markdown:\n' + args.schema.read_text()
    for image in args.image:
        prompt += '\nInspect the supplied reference image with your image-reading tool: ' + str(image)
    if args.harness == 'deepseek-harness':
        patch = [{'id':'agent-default-model','config':{'provider':'deepseek-official','model':args.model}},
                 {'id':'llm-deepseek','config':{'baseURL':base+'/v1','apiKeyEnv':'DEEPSEEK_API_KEY',
                    'reasoningEffort':args.effort,'maxTokens':65536,
                    'models':[{'id':args.model,'inputModalities':['text','image']}]}},
                 *[{'id':name,'disabled':True} for name in ('session-title-llm','tool-subagent','tool-subagent-fork')]]
        path=home/'benchmark.json';private_json(path,patch)
        env.update(DSH_HOME=str(home),DEEPSEEK_API_KEY=key)
        return [args.native_bin,'--profile','headless','--patch',str(path),'--json','-'],prompt,env
    if args.harness == 'kimi-codecli':
        # TOML strings use JSON escaping, which is also valid for these strings.
        q=json.dumps
        config='\n'.join(['default_model = '+q(args.model),'default_permission_mode = "yolo"',
            '[providers.gw]','type = "openai"','base_url = '+q(base+'/v1'),'api_key_env = "CODEX_API_KEY"',
            '[models.'+q(args.model)+']','provider = "gw"','model = '+q(args.model),
            'max_context_size = 262144','capabilities = ["image_in", "thinking"]'])
        (home/'config.toml').write_text(config)
        env.update(KIMI_CODE_HOME=str(home),KIMI_MODEL_THINKING_EFFORT=args.effort,KIMI_CODE_WATCH='0')
        return [args.native_bin,'-p',prompt,'--output-format','stream-json','-m',args.model],None,env
    if args.harness == 'zcode':
        rules={'schemaVersion':1,'config':{
            'providerConfigRules':{'providerRules':[{'providerId':'gw','providerName':'Gateway','enabled':True,
                'config':{'group':'standard-personal','access':{'type':'api-key','apiKey':key},
                    'api':{'type':'openai-chat-completions','baseUrl':base+'/v1','headers':{}},
                    'personalModelIds':[args.model],'modelOrder':[args.model],'visibility':'visible'}}]},
            'modelConfigRules':{'providerModelRules':[{'providerId':'gw','modelId':args.model,'config':{
                'enabled':True,'properties':{'contextWindow':200000,'supportsToolCall':True,
                    'inputFormat':{'supportsText':True,'supportsImage':True}},
                'optionSpecs':{'maxOutputTokens':{'max':65536,'map':'{"max_tokens": maxOutputTokens}'},
                    'reasoningLevel':{'values':['high','xhigh','max'],'map':'{"reasoning_effort": reasoningLevel}'}}}}],
                'manualProviderModelRules':[]},
            'defaultModelSelection':{'providerId':'gw','modelId':args.model,'options':{'reasoningLevel':args.effort}}}}
        path=home/'provider_config.json';private_json(path,rules)
        env.update(ZCODE_DATA_BASE_DIR=str(home),ZCODE_CLI_SETTINGS_FILE=str(home/'settings.json'),
            ZCODE_PERSONAL_PROVIDER_CONFIG_FILE=str(path),ZCODE_CLI_CREDENTIALS_FILE=str(home/'credentials.json'),
            ZCODE_SESSION_DB_PATH=str(home/'db.sqlite'),ZCODE_DISABLE_UPDATE_CHECK='1',ZCODE_MODEL_RETRY_MAX_RETRIES='0')
        command=[args.native_bin,'--json','--model','gw/'+args.model,'--effort',args.effort,
                 '--mode','yolo','--cwd',str(Path.cwd())]
        for image in args.image:command+=['--attach',str(image)]
        return command+['-p',prompt],None,env
    if args.harness == 'gemini-cli':
        if args.effort!='high':raise ValueError('Gemini contract requires high effort')
        # Gemini 3 defaults to HIGH; a private settings file keeps native defaults isolated.
        private_json(home/'.gemini/settings.json',{'security':{'auth':{'selectedType':'gemini-api-key'}},
                     'model':{'name':args.model},'telemetry':{'enabled':False}})
        env.update(HOME=str(home),GEMINI_API_KEY=key,GOOGLE_GEMINI_BASE_URL=base)
        return [args.native_bin,'--model',args.model,'--approval-mode','yolo','--output-format','stream-json','-p',prompt],None,env
    raise ValueError('Unsupported native harness: '+args.harness)


def decode_final(text, structured):
    if structured is not None:return structured
    if not isinstance(text,str) or not text.strip():raise ValueError('No final response')
    value=text.strip()
    if value.startswith('```'):value=value.split('\n',1)[1].rsplit('```',1)[0].strip()
    try:return json.loads(value)
    except ValueError:return value


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('harness','model','base-url','effort','native-bin'):p.add_argument('--'+name,required=True)
    for name in ('session','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--schema',type=Path);p.add_argument('--image',type=Path,action='append',default=[])
    p.add_argument('--allow-shell',action='store_true')
    args=p.parse_args();command,prompt,env=command_for(args,sys.stdin.read())
    # Outer process group owns timeout and retry; this adapter makes one CLI call.
    process=subprocess.Popen(command,stdin=subprocess.PIPE if prompt is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,stderr=None,text=True,env=env,bufsize=1)
    if prompt is not None:process.stdin.write(prompt);process.stdin.close()
    final=None;structured=None;terminal=False;failed=False;raw=[]
    with (args.session/'native-events.jsonl').open('w') as log:
        for line in process.stdout:
            log.write(line);log.flush();raw.append(line)
            print(line,end='',flush=True)
            try:event=json.loads(line)
            except ValueError:continue
            if not isinstance(event,dict):continue
            kind=event.get('type');usage=None
            sid=event.get('sessionId') or event.get('session_id')
            if sid:print(json.dumps({'type':'thread.started','thread_id':sid}),flush=True)
            if args.harness=='deepseek-harness':
                if kind=='final':terminal=True;final=event.get('text')
                if event.get('phase')=='step_end':
                    u=event.get('usage') or {}
                    if 'inputTokens' in u and 'outputTokens' in u:usage={
                        'input_tokens':u['inputTokens'],'output_tokens':u['outputTokens'],
                        'cached_input_tokens':u.get('cacheReadTokens'),'reasoning_output_tokens':u.get('reasoningTokens')}
            elif args.harness=='kimi-codecli':
                if event.get('role')=='assistant' and not event.get('tool_calls'):
                    content=event.get('content');final=''.join(v.get('text','') for v in content if isinstance(v,dict)) if isinstance(content,list) else content
                    terminal=bool(final)
                usage=event.get('usage')
            elif args.harness=='zcode':
                if isinstance(event.get('response'),str):final=event['response'];terminal=True
                u=event.get('usage') or {}
                if 'inputTokens' in u and 'outputTokens' in u:usage={'input_tokens':u['inputTokens'],'output_tokens':u['outputTokens'],'cached_input_tokens':u.get('cacheReadTokens')}
            elif args.harness=='gemini-cli':
                if kind=='message' and event.get('role')=='assistant':final=(final or '')+event.get('content','')
                if kind=='result':
                    terminal=event.get('status')=='success';failed=not terminal;u=event.get('stats') or {}
                    if 'input_tokens' in u and 'output_tokens' in u:usage={'input_tokens':u['input_tokens'],'output_tokens':u['output_tokens'],'cached_input_tokens':u.get('cached')}
            if isinstance(usage,dict) and 'input_tokens' in usage and 'output_tokens' in usage:
                print(json.dumps({'type':'turn.completed','usage':usage}),flush=True)
    code=process.wait()
    if args.harness=='zcode' and not terminal:
        try:
            event=json.loads(''.join(raw));final=event.get('response');terminal=isinstance(final,str)
        except ValueError:pass
    if code or failed or not terminal:raise RuntimeError('Native CLI did not deliver a successful final result; inspect retained events')
    value=decode_final(final,structured)
    if args.schema and not isinstance(value,dict):raise ValueError('Final response is not the required JSON bundle')
    args.output.write_text(json.dumps(value) if isinstance(value,dict) else value)


if __name__=='__main__':main()
