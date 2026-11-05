"""Private host-side model gateway + container TCP bridge over a Unix socket.

The authoring container has --network none. Only Responses/model-list calls to
the configured provider are forwarded; the API credential stays on the host.
"""
import argparse
import gzip
import hashlib
import http.client
import http.server
import json
import os
import re
import time
import uuid
try:
    from .l3_usage import UsageParser, append_record
    from .l3_api_control import api_slot, BalanceExhausted, is_balance_error, mark_balance_exhausted, is_transient
except ImportError:
    from l3_usage import UsageParser, append_record
    from l3_api_control import api_slot, BalanceExhausted, is_balance_error, mark_balance_exhausted, is_transient
if os.environ.get("L3_MULTIMODEL_GATEWAY") == "1":
    from tools.l3_batch_control import api_slot, mark_balance_exhausted, observe_status, MultiUsageParser
    UsageParser = MultiUsageParser

from pathlib import Path
import select
import socket
import socketserver
import threading
import urllib.parse


class ThreadedUnix(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def upstream_headers(incoming, credential):
    # HTTP header names are case-insensitive. A plain dict otherwise preserves
    # duplicate content-type/Content-Type fields rejected by some providers.
    denied={'host','authorization','connection','content-length','transfer-encoding','proxy-authorization','content-type','x-api-key','x-goog-api-key','accept-encoding'}
    result={k.lower():v for k,v in incoming.items() if k.lower() not in denied}
    result['authorization']='Bearer '+credential
    result['content-type']='application/json'
    # Relay and usage parser consume plaintext; never negotiate client compression.
    result['accept-encoding']='identity'
    return result


def image_count(value):
    if isinstance(value,list):return sum(image_count(v) for v in value)
    if not isinstance(value,dict):return 0
    present=(isinstance(value.get('type'),str) and value.get('type') in {'input_image','image','image_url'} and any(k in value for k in ['source','image_url','data'])) or any(k in value for k in ('inlineData','inline_data'))
    return int(present)+sum(image_count(v) for v in value.values())


def model_payload(body, route, environment):
    if not body or not environment.get('L3_EXPECTED_MODEL'):return body
    payload=json.loads(body)
    if route.startswith('/v1beta/'):
        if ':countTokens' not in route:payload.setdefault('generationConfig',{}).setdefault('thinkingConfig',{})['thinkingLevel']='HIGH'
        return json.dumps(payload,separators=(',',':')).encode()
    payload['model']=environment['L3_EXPECTED_MODEL']
    effort=environment.get('L3_EXPECTED_EFFORT','high')
    if route=='/v1/responses':payload.setdefault('reasoning',{})['effort']=effort
    elif route=='/v1/messages':payload.setdefault('output_config',{})['effort']=effort
    elif route=='/v1/chat/completions':payload['reasoning_effort']=effort
    return json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()



def request_wire_body(body, headers, compress=False):
    """Lossless transport compression; image bytes and JSON values are unchanged."""
    headers=dict(headers)
    if body is not None:
        if compress and len(body)>=256*1024:
            packed=gzip.compress(body,compresslevel=1,mtime=0)
            if len(packed)<len(body):
                body=packed
                headers['content-encoding']='gzip'
        headers['content-length']=str(len(body))
    return body,headers


def retryable_ingress_rejection(status, detail):
    # Provider confirmed this specific error is rejected before model dispatch.
    return status==400 and 'truncated_body' in str(detail).lower()


def process_identity(pid):
    try:
        raw=Path(f'/proc/{pid}/stat').read_text()
        fields=raw[raw.rfind(')')+2:].split()
        return None if fields[0]=='Z' else fields[19]
    except (OSError,IndexError):return None


def serve(path, provider, ledger=None, stage_file=None, publish_socket=None, watch_pid=None):
    config = json.loads(Path(provider).read_text())
    endpoint = urllib.parse.urlsplit(config['base_url'])
    if endpoint.scheme != 'https' or endpoint.query or endpoint.fragment:
        raise ValueError('Provider must be a fixed HTTPS base URL')
    prefix = endpoint.path.rstrip('/')

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def do_POST(self):
            self.forward()

        def do_GET(self):
            self.forward()

        def forward(self):
            try:
                with api_slot():self.forward_reserved()
            except BalanceExhausted:
                raw=b'{"error":{"code":"insufficient_quota","message":"API balance exhausted; batch stopped"}}'
                self.send_response(402);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)

        def forward_reserved(self):
            route = urllib.parse.urlsplit(self.path).path
            allowed = {('POST', '/v1/responses'), ('POST', '/v1/responses/compact'), ('GET', '/v1/models')}
            if os.environ.get('L3_MULTIMODEL_GATEWAY') == '1':allowed |= {('POST','/v1/messages'),('POST','/v1/messages/count_tokens'),('POST','/v1/chat/completions')}
            expected=os.environ.get('L3_EXPECTED_MODEL','')
            google_route=(self.command=='POST' and expected.startswith('gemini-') and
                          re.fullmatch(r'/v1beta/models/'+re.escape(expected)+r':(?:generateContent|streamGenerateContent|countTokens)',route) is not None)
            if (self.command, route) not in allowed and not google_route:
                print(json.dumps({'event':'gateway_rejected','time':time.time(),'path':self.path,'reason':'route','status':403}),flush=True)
                self.send_error(403, 'Only the fixed model API is available')
                return
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0 or length > 256 * 1024 * 1024:
                print(json.dumps({'event':'gateway_rejected','time':time.time(),'path':self.path,'reason':'body_size','bytes':length,'status':413}),flush=True)
                self.send_error(413)
                return
            body = self.rfile.read(length) if length else None
            if body is not None and len(body)!=length:
                print(json.dumps({'event':'gateway_rejected','time':time.time(),'path':self.path,'reason':'incomplete_client_body','expected_bytes':length,'received_bytes':len(body),'status':400}),flush=True)
                self.send_error(400,'Incomplete request body')
                self.close_connection=True
                return
            body = model_payload(body, route, os.environ)
            attempt=uuid.uuid4().hex; started=time.time(); parser=UsageParser()
            stage=Path(stage_file).read_text().strip() if stage_file and Path(stage_file).exists() else 'unspecified'
            model=None
            if body:
                try:model=json.loads(body).get('model')
                except (ValueError,AttributeError):pass
            audit={'image_count':image_count(json.loads(body)) if body else 0,'attempt_id':attempt,'stage':stage,'started_unix':started,'path':self.path,'model':model,'reasoning_effort':os.environ.get('L3_EXPECTED_EFFORT','high') if os.environ.get('L3_EXPECTED_MODEL') and self.command=='POST' else None}
            append_record(ledger,dict(audit,event='request_started'))
            status=None; transport_error=None; request_id=None; first_byte=None
            conn = http.client.HTTPSConnection(endpoint.hostname, endpoint.port or 443, timeout=600)
            try:
                headers=upstream_headers(self.headers,config['api_key'])
                if route.startswith('/v1/messages'):headers['x-api-key']=config['api_key']
                if google_route:headers['x-goog-api-key']=config['api_key']
                wire_body,headers=request_wire_body(body,headers,config.get('request_compression')=='gzip' and route in config.get('request_compression_routes',['/v1/messages','/v1/responses','/v1/chat/completions']))
                audit.update(request_body_bytes=len(body or b''),wire_body_bytes=len(wire_body or b''),request_body_sha256=hashlib.sha256(body or b'').hexdigest(),request_content_encoding=headers.get('content-encoding','identity'))
                append_record(ledger,dict(audit,event='request_transport_started'))
                transport_started=time.monotonic()
                conn.connect()
                audit['connect_seconds']=time.monotonic()-transport_started
                upload_started=time.monotonic()
                target=(prefix.removesuffix('/v1')+route+('?alt=sse' if ':streamGenerateContent' in route else '')) if google_route else prefix+self.path.removeprefix('/v1')
                conn.request(self.command, target, body=wire_body, headers=headers)
                audit['upload_seconds']=time.monotonic()-upload_started
                response = conn.getresponse()
                audit['response_headers_seconds']=time.monotonic()-transport_started
                status=response.status;request_id=response.getheader('x-request-id')
                if os.environ.get('L3_MULTIMODEL_GATEWAY')=='1':observe_status(status)
                if response.status >= 400:
                    raw=response.read(65536)
                    content=raw.decode('utf-8',errors='replace')
                    try:
                        parsed=json.loads(content);detail=parsed.get('error',parsed)
                    except (ValueError,AttributeError):
                        title=re.search(r'<title[^>]*>(.*?)</title>',content,re.I|re.S)
                        detail={'html_title':title.group(1).strip() if title else 'Non-JSON provider error'}
                    if is_balance_error(response.status,detail):mark_balance_exhausted(response.status,model,request_id)
                    raw=raw.replace(config['api_key'].encode(),b'[REDACTED]')
                    # Log only provider failures, never prompts, successful bodies, or credentials.
                    safe=json.dumps(detail,ensure_ascii=False).replace(config['api_key'],'[REDACTED]')[:1600]
                    print(json.dumps({'time':time.time(),'status':response.status,'path':self.path,
                          'request_id':response.getheader('x-request-id'),'detail':safe}),flush=True)
                    # Slow native client retry bursts during provider outages.
                    if not is_balance_error(response.status,detail) and (response.status==429 or response.status>=500 or is_transient(detail)):time.sleep(30)
                    client_status=502 if retryable_ingress_rejection(response.status,detail) else response.status
                    audit['client_http_status']=client_status
                    self.send_response(client_status)
                    self.send_header('Content-Type',response.getheader('Content-Type','application/json'))
                    self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
                    return
                self.send_response(response.status)
                self.send_header('Content-Type', response.getheader('Content-Type', 'application/json'))
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()
                while True:
                    data = response.read1(65536)
                    if not data:
                        break
                    if first_byte is None:first_byte=time.time()-started
                    parser.feed(data)
                    self.wfile.write(('%x\r\n' % len(data)).encode() + data + b'\r\n')
                    self.wfile.flush()
                self.wfile.write(b'0\r\n\r\n')
                self.wfile.flush()
            except (OSError, http.client.HTTPException) as error:
                transport_error=type(error).__name__
                self.close_connection = True
            finally:
                conn.close()
                parser.finish()
                append_record(ledger,dict(audit,event='request_finished',finished_unix=time.time(),
                    elapsed_seconds=time.time()-started,http_status=status,request_id=request_id,
                    first_body_byte_seconds=first_byte,transport_error=transport_error,
                    response_id=parser.response_id,usage=parser.usage,terminal_event=parser.terminal_event,
                    parser_overflow=parser.overflow))

    server = ThreadedUnix(str(path), Handler)
    os.chmod(path, 0o600)
    if watch_pid:
        identity=process_identity(watch_pid)
        if identity is None:
            server.server_close()
            Path(path).unlink(missing_ok=True)
            raise RuntimeError('Owning worker is no longer live')
        def watch_owner():
            while process_identity(watch_pid)==identity:time.sleep(2)
            # This replacement gateway belongs only to the original live worker.
            os._exit(0)
        threading.Thread(target=watch_owner,daemon=True).start()
    if publish_socket:
        # Atomic pathname switch preserves all connections to the old listener.
        os.replace(path,publish_socket)
    server.serve_forever()


def bridge(path, port):
    class Relay(socketserver.BaseRequestHandler):
        def handle(self):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as upstream:
                upstream.connect(str(path))
                peers = {self.request: upstream, upstream: self.request}
                while True:
                    ready, _, _ = select.select(list(peers), [], [], 660)
                    if not ready:
                        return
                    for source in ready:
                        data = source.recv(65536)
                        if not data:
                            return
                        peers[source].sendall(data)
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True
    Server(('127.0.0.1', port), Relay).serve_forever()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['serve', 'bridge'])
    p.add_argument('--socket', type=Path, required=True)
    p.add_argument('--provider', type=Path)
    p.add_argument('--ledger',type=Path)
    p.add_argument('--stage-file',type=Path)
    p.add_argument('--port', type=int, default=8765)
    p.add_argument('--publish-socket',type=Path)
    p.add_argument('--watch-pid',type=int)
    a = p.parse_args()
    if a.mode == 'serve':
        if not a.provider:
            p.error('--provider is required for the private gateway')
        serve(a.socket, a.provider, a.ledger, a.stage_file, a.publish_socket, a.watch_pid)
    else:
        bridge(a.socket, a.port)
