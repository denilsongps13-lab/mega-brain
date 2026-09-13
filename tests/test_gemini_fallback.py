"""Real pinned LiteLLM Router/provider adapters; loopback HTTP, synthetic keys only."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import litellm
import pytest
from litellm import Router

ROOT = Path(__file__).resolve().parents[1]

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

launcher = load('start_mega_brain')
rate = load('mega_brain_rate_limit')


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    state = {'gemini': 0, 'groq': 0, 'status': 200, 'groq_status': 200, 'bodies': []}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            provider = 'gemini' if '/models/gemini-' in self.path else 'groq'
            state[provider] += 1
            state['bodies'].append((provider, body))
            status = state['status'] if provider == 'gemini' else state['groq_status']
            self.send_response(status)
            streaming = body.get('stream') or 'streamGenerateContent' in self.path
            self.send_header('Content-Type', 'text/event-stream' if streaming and status == 200 else 'application/json')
            self.end_headers()
            if status != 200:
                data = {'error': {'code': status, 'message': 'synthetic provider failure',
                                  'status': 'RESOURCE_EXHAUSTED' if status == 429 else 'UNAVAILABLE'}}
            elif provider == 'gemini':
                data = {'candidates': [{'content': {'role': 'model', 'parts': [{'text': 'GEMINI OK'}]},
                                        'finishReason': 'STOP'}],
                        'usageMetadata': {'promptTokenCount': 5, 'candidatesTokenCount': 3, 'totalTokenCount': 8}}
            else:
                data = {'id': 'test-groq', 'object': 'chat.completion', 'created': 1,
                        'model': 'openai/gpt-oss-120b',
                        'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'GROQ OK'},
                                     'finish_reason': 'stop'}],
                        'usage': {'prompt_tokens': 5, 'completion_tokens': 3, 'total_tokens': 8}}
            if provider == 'groq' and status == 200 and state.get('tool_reply'):
                data['choices'][0]['message'] = {'role':'assistant', 'content':None,
                    'tool_calls':[{'id':'call_fixture', 'type':'function', 'function':{
                        'name':'lookup', 'arguments':'{\"query\":\"fixture\"}'}}]}
                data['choices'][0]['finish_reason'] = 'tool_calls'
            if streaming and status == 200:
                if provider == 'groq':
                    choice = data['choices'][0]
                    choice['delta'] = choice.pop('message')
                    data['object'] = 'chat.completion.chunk'
                self.wfile.write(('data: ' + json.dumps(data) + '\n\n').encode())
                if provider == 'groq':
                    self.wfile.write(b'data: [DONE]\n\n')
            else:
                self.wfile.write(json.dumps(data).encode())
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state['url'] = f'http://127.0.0.1:{server.server_port}'
    config = launcher.proxy_config(launcher.MODEL)
    for model in config['model_list']:
        model['litellm_params']['api_key'] = 'synthetic-test-key'
        model['litellm_params']['api_base'] = state['url']
    monkeypatch.setattr(litellm, 'callbacks', [])
    monkeypatch.setattr(litellm, 'num_retries', 0)
    monkeypatch.setattr(litellm, 'drop_params', True)
    monkeypatch.setattr(litellm, 'use_chat_completions_url_for_anthropic_messages', True)
    router = Router(model_list=config['model_list'], **config['router_settings'])
    yield router, state
    server.shutdown()
    server.server_close()
    thread.join()


async def ask(router):
    return await router.aanthropic_messages(model=launcher.MODEL, max_tokens=32,
                messages=[{'role': 'user', 'content': 'test'}])


def response_text(result):
    return json.dumps(result if isinstance(result, dict) else result.model_dump())


def test_primary_no_startup_inference(bridge):
    router, state = bridge
    assert state['gemini'] == state['groq'] == 0
    result = asyncio.run(ask(router))
    assert 'GEMINI OK' in response_text(result)
    assert (state['gemini'], state['groq']) == (1, 0)


@pytest.mark.parametrize('status', [429, 503])
def test_provider_failure_falls_back_once_and_primary_recovers(bridge, status):
    router, state = bridge
    state['status'] = status
    async def scenario():
        assert 'GROQ OK' in response_text(await ask(router))
        state['status'] = 200
        assert 'GEMINI OK' in response_text(await ask(router))
    asyncio.run(scenario())
    assert (state['gemini'], state['groq']) == (2, 1)


def test_no_local_sixth_request_throttle(bridge):
    router, state = bridge
    async def scenario():
        for _ in range(6):
            assert 'GEMINI OK' in response_text(await ask(router))
    asyncio.run(scenario())
    assert (state['gemini'], state['groq']) == (6, 0)


def test_both_down_stop_without_retry_loop(bridge):
    router, state = bridge
    state['status'] = state['groq_status'] = 503
    with pytest.raises(Exception):
        asyncio.run(ask(router))
    assert (state['gemini'], state['groq']) == (1, 1)


def test_legacy_sliding_limiter_is_atomic_but_not_launcher_loaded(tmp_path):
    now = [100.0]
    database = tmp_path / 'rate.sqlite'
    deployment = {'litellm_params': {'model': launcher.MODEL}}
    def reserve(_):
        guard = rate.GeminiRateLimit(database, clock=lambda: now[0])
        try:
            guard.pre_call_check(deployment)
            return True
        except litellm.RateLimitError:
            return False
    with ThreadPoolExecutor(max_workers=10) as pool:
        assert sum(pool.map(reserve, range(20))) == 5
    now[0] = 160.01
    assert reserve(0)
    config = launcher.proxy_config(launcher.MODEL)
    assert 'callbacks' not in config['litellm_settings']
    assert 'cooldown_time' not in config['router_settings']
    assert 'enable_pre_call_checks' not in config['router_settings']
    for entry in config['model_list']:
        assert 'rpm' not in entry['litellm_params']


def test_keys_only_from_local_fixture_and_never_in_client(tmp_path, monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', 'inherited-must-not-be-used')
    (tmp_path / '.env').write_text('GEMINI_API_KEY=synthetic-gemini\nGROQ_API_KEY=synthetic-groq\n')
    assert launcher.load_provider_keys(tmp_path) == {
        'GEMINI_API_KEY': 'synthetic-gemini', 'GROQ_API_KEY': 'synthetic-groq'}
    env = launcher.sanitized_client_environment({'GEMINI_API_KEY': 'fake',
        'GROQ_API_KEY': 'fake', 'GOOGLE_API_KEY': 'fake', 'PATH': 'keep'})
    assert env == {'PATH': 'keep'}
    (tmp_path / '.env').write_text('GEMINI_API_KEY=synthetic-gemini\n')
    with pytest.raises(launcher.StartupError):
        launcher.load_provider_keys(tmp_path)


@pytest.mark.parametrize('fail_primary', [False, True])
def test_anthropic_streaming(bridge, fail_primary):
    router, state = bridge
    if fail_primary:
        state['status'] = 429
    async def scenario():
        stream = await router.aanthropic_messages(model=launcher.MODEL, max_tokens=32,
            stream=True, messages=[{'role':'user', 'content':'test'}])
        chunks = []
        async for chunk in stream:
            chunks.append(str(chunk))
        return ''.join(chunks)
    content = asyncio.run(scenario())
    assert 'message_start' in content and 'message_stop' in content
    assert ('GROQ OK' if fail_primary else 'GEMINI OK') in content
    assert state['gemini'] == 1
    assert state['groq'] == int(fail_primary)


def test_real_proxy_provider_429_falls_back_and_recovers(bridge, tmp_path):
    import subprocess
    import sys
    import urllib.error
    import yaml
    _, state = bridge
    config = launcher.proxy_config(launcher.MODEL)
    for entry in config['model_list']:
        entry['litellm_params']['api_base'] = state['url']
    config_path = tmp_path / 'proxy.yaml'
    config_path.write_text(yaml.safe_dump(config))
    env = {k:v for k,v in os.environ.items() if k.upper() in {
        'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','HOME','USERPROFILE','COMSPEC'}}
    env.update(PYTHONPATH=str(ROOT), PYTHONUTF8='1', LITELLM_TELEMETRY='False',
        LITELLM_LOCAL_MODEL_COST_MAP='True', GEMINI_API_KEY='synthetic-gemini', GROQ_API_KEY='synthetic-groq',
        MEGA_BRAIN_GATEWAY_TOKEN='sk-synthetic-gateway')
    port = launcher.select_port()
    url = f'http://127.0.0.1:{port}'
    with (tmp_path / 'proxy-test.log').open('wb') as log:
        process = subprocess.Popen([sys.executable, '-c',
            'from litellm import run_server; run_server()', '--config', str(config_path),
            '--host', '127.0.0.1', '--port', str(port)], cwd=tmp_path, env=env,
            stdout=log, stderr=log)
        try:
            launcher.wait_ready(process, url, 'sk-synthetic-gateway')
            assert state['gemini'] == state['groq'] == 0
            payload = {'model':launcher.MODEL,'max_tokens':32,
                'messages':[{'role':'user','content':'test'}]}
            with pytest.raises(urllib.error.HTTPError):
                launcher.request(url + '/v1/messages', 'sk-wrong', payload)
            state['status'] = 429
            with launcher.request(url + '/v1/messages', 'sk-synthetic-gateway', payload) as response:
                assert 'GROQ OK' in response.read().decode()
            state['status'] = 200
            with launcher.request(url + '/v1/messages', 'sk-synthetic-gateway', payload) as response:
                assert 'GEMINI OK' in response.read().decode()
            assert (state['gemini'], state['groq']) == (2, 1)
        finally:
            launcher.stop_owned(process)


def test_fallback_preserves_anthropic_tool_use_and_tool_results(bridge):
    router, state = bridge
    state.update(status=429, tool_reply=True)
    tools = [{'name':'lookup','description':'Local fixture lookup',
        'input_schema':{'type':'object','properties':{'query':{'type':'string'}},'required':['query']}}]
    messages = [{'role':'user','content':'test tool'}]
    async def scenario():
        first = await router.aanthropic_messages(model=launcher.MODEL, max_tokens=128,
            tools=tools, messages=messages)
        content = first['content'] if isinstance(first,dict) else first.content
        assert content[0]['type'] == 'tool_use'
        assert content[0]['name'] == 'lookup'
        assert content[0]['input'] == {'query':'fixture'}
        messages.extend([{'role':'assistant','content':content},
            {'role':'user','content':[{'type':'tool_result','tool_use_id':content[0]['id'],
                                      'content':'fixture result'}]}])
        state['tool_reply'] = False
        assert 'GROQ OK' in response_text(await router.aanthropic_messages(
            model=launcher.MODEL, max_tokens=128, tools=tools, messages=messages))
    asyncio.run(scenario())
    body = state['bodies'][-1][1]
    assert any(m.get('role') == 'tool' and m.get('content') == 'fixture result' for m in body['messages'])
    assert body['tools'][0]['function']['name'] == 'lookup'
