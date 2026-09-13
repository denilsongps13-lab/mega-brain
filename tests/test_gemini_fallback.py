"""Real pinned LiteLLM Router/provider adapters; loopback HTTP, synthetic keys only."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
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
                        'model': 'llama-3.3-70b-versatile',
                        'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'GROQ OK'},
                                     'finish_reason': 'stop'}],
                        'usage': {'prompt_tokens': 5, 'completion_tokens': 3, 'total_tokens': 8}}
            if provider == 'groq' and status == 200 and state.get('tool_reply'):
                data['choices'][0]['message'] = {'role':'assistant', 'content':None,
                    'tool_calls':[{'id':'call_fixture', 'type':'function', 'function':{
                        'name':'lookup', 'arguments':'{"query":"fixture"}'}}]}
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
        model['litellm_params']['api_base'] = f'http://127.0.0.1:{server.server_port}'
    guard = rate.GeminiRateLimit(tmp_path / 'rate.sqlite')
    monkeypatch.setattr(litellm, 'callbacks', [guard])
    monkeypatch.setattr(litellm, 'num_retries', 0)
    monkeypatch.setattr(litellm, 'drop_params', True)
    monkeypatch.setattr(litellm, 'use_chat_completions_url_for_anthropic_messages', True)
    router = Router(model_list=config['model_list'], **config['router_settings'])
    yield router, state, guard
    server.shutdown()
    server.server_close()
    thread.join()


async def ask(router):
    return await router.aanthropic_messages(model=launcher.MODEL, max_tokens=32,
                messages=[{'role': 'user', 'content': 'test'}])


def response_text(result):
    return json.dumps(result if isinstance(result, dict) else result.model_dump())


def test_primary_no_startup_inference(bridge):
    router, state, _ = bridge
    assert state['gemini'] == state['groq'] == 0
    result = asyncio.run(ask(router))
    assert 'GEMINI OK' in response_text(result)
    assert (state['gemini'], state['groq']) == (1, 0)


@pytest.mark.parametrize('status', [429, 503])
def test_failure_falls_back_once_and_cooldown_recovers(bridge, status):
    router, state, _ = bridge
    state['status'] = status
    async def scenario():
        assert 'GROQ OK' in response_text(await ask(router))
        await asyncio.sleep(.2)  # let Router's asynchronous failure logger finish
        state['status'] = 200
        assert 'GROQ OK' in response_text(await ask(router))
        assert state['gemini'] == 1
        # Expire only the Router cooldown cache: deterministic 61-second recovery.
        router.cooldown_cache.cache.flush_cache()
        assert 'GEMINI OK' in response_text(await ask(router))
    asyncio.run(scenario())
    assert (state['gemini'], state['groq']) == (2, 2)


def test_sixth_request_uses_groq_without_contacting_gemini(bridge):
    router, state, _ = bridge
    async def scenario():
        for _ in range(5):
            assert 'GEMINI OK' in response_text(await ask(router))
        assert 'GROQ OK' in response_text(await ask(router))
    asyncio.run(scenario())
    assert (state['gemini'], state['groq']) == (5, 1)


def test_both_down_stop_without_retry_loop(bridge):
    router, state, _ = bridge
    state['status'] = state['groq_status'] = 503
    with pytest.raises(Exception):
        asyncio.run(ask(router))
    assert (state['gemini'], state['groq']) == (1, 1)


def test_persistent_sliding_limit_is_atomic_and_recovers(tmp_path):
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
    now[0] = 159.99
    assert not reserve(0)
    now[0] = 160.01
    assert reserve(0)
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 1


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
    router, state, _ = bridge
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


def test_real_proxy_loads_guard_and_auth_without_provider_warmup(bridge, tmp_path):
    import subprocess
    import sys
    import urllib.error
    import yaml
    router, state, _ = bridge
    config = launcher.proxy_config(launcher.MODEL)
    for entry in config['model_list']:
        entry['litellm_params']['api_base'] = state['url']
    config_path = tmp_path / 'proxy.yaml'
    config_path.write_text(yaml.safe_dump(config))
    # Explicit system essentials only. No inherited provider credentials or .env.
    env = {k:v for k,v in os.environ.items() if k.upper() in {
        'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','HOME','USERPROFILE','COMSPEC'}}
    env.update(PYTHONPATH=str(ROOT), PYTHONUTF8='1', LITELLM_TELEMETRY='False',
        LITELLM_LOCAL_MODEL_COST_MAP='True', GEMINI_API_KEY='synthetic-gemini', GROQ_API_KEY='synthetic-groq',
        MEGA_BRAIN_GATEWAY_TOKEN='sk-synthetic-gateway',
        MEGA_BRAIN_RATE_DB=str(tmp_path / 'proxy-rate.sqlite'))
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
            with pytest.raises(urllib.error.HTTPError) as error:
                launcher.request(url + '/v1/messages', 'sk-wrong', payload)
            # A proxy without a token database rejects unknown tokens with 400.
            assert error.value.code in (400, 401)
            assert state['gemini'] == state['groq'] == 0
            for index in range(6):
                with launcher.request(url + '/v1/messages', 'sk-synthetic-gateway', payload) as response:
                    data = response.read().decode()
                assert ('GEMINI OK' if index < 5 else 'GROQ OK') in data
            assert (state['gemini'],state['groq']) == (5,1)
        finally:
            launcher.stop_owned(process)


def test_fallback_preserves_anthropic_tool_use_and_tool_results(bridge):
    router, state, _ = bridge
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
