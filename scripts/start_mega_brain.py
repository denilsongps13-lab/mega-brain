"""Windows launcher: existing hooks -> portable runner; Claude -> local LiteLLM -> Gemini.
Never prints provider credentials or raw provider/CLI error bodies.
"""
from __future__ import annotations

import argparse
import copy
import importlib.metadata
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import sysconfig
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'gemini/gemini-3.6-flash'
# Groq fallback used only when Gemini cannot serve the request.
FALLBACK_MODEL = 'openai/gpt-oss-120b'
KEY_NAMES = ('GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GOOGLE_GENERATIVE_AI_API_KEY')


class StartupError(Exception):
    pass


def load_provider_keys(root):
    from dotenv import dotenv_values
    values = dotenv_values(root / '.env', interpolate=False, encoding='utf-8-sig')
    gemini = next((values[n].strip() for n in KEY_NAMES if (values.get(n) or '').strip()), None)
    groq = (values.get('GROQ_API_KEY') or '').strip()
    if not gemini or not groq:
        raise StartupError('GEMINI_API_KEY ou GROQ_API_KEY ausente no .env local. Arquivo preservado.')
    return {'GEMINI_API_KEY': gemini, 'GROQ_API_KEY': groq}


def load_provider_key(root):
    from dotenv import dotenv_values
    values = dotenv_values(root / '.env', interpolate=False, encoding='utf-8-sig')
    for name in KEY_NAMES:
        if values.get(name):
            return values[name].strip()
    raise StartupError('Chave Gemini ausente no .env local.')


def sanitized_client_environment(env):
    result = dict(env)
    for name in (*KEY_NAMES, 'GROQ_API_KEY', 'LITELLM_MASTER_KEY', 'MEGA_BRAIN_GATEWAY_TOKEN'):
        result.pop(name, None)
    return result


def find_bash(env):
    candidates = []
    if env.get('CLAUDE_CODE_GIT_BASH_PATH'):
        candidates.append(Path(env['CLAUDE_CODE_GIT_BASH_PATH']))
    git = shutil.which('git', path=env.get('PATH'))
    if git:
        base = Path(git).resolve().parent.parent
        candidates += [base / 'bin/bash.exe', base / 'usr/bin/bash.exe']
    for var, suffix in [('ProgramFiles', 'Git'), ('ProgramFiles(x86)', 'Git'), ('LOCALAPPDATA', 'Programs/Git')]:
        if env.get(var):
            base = Path(env[var]) / suffix
            candidates += [base / 'bin/bash.exe', base / 'usr/bin/bash.exe']
    if os.name != 'nt' and shutil.which('bash'):
        candidates.append(Path(shutil.which('bash')))
    for p in candidates:
        if p.is_file():
            probe = subprocess.run([str(p), '--version'], capture_output=True, timeout=10)
            if probe.returncode == 0:
                return p.resolve()
    raise StartupError('Git Bash nao encontrado. Repare a instalacao do Git for Windows.')


def child_environment(base, bash):
    env = dict(base)
    env.update(MEGA_BRAIN_PYTHON=sys.executable, CLAUDE_CODE_GIT_BASH_PATH=str(bash), CLAUDE_PROJECT_DIR=str(ROOT), PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    directories = [str(Path(sys.executable).parent), sysconfig.get_path('scripts'), str(bash.parent)]
    if os.name == 'nt':
        git_root = bash.parent.parent if bash.parent.name == 'bin' else bash.parent
        if git_root.name == 'usr':
            git_root = git_root.parent
        directories += [str(git_root / 'bin'), str(git_root / 'usr/bin')]
    env['PATH'] = os.pathsep.join(directories + [env.get('PATH', '')])
    return env


def hook_target(command):
    patterns = [
        r'bash "\$CLAUDE_PROJECT_DIR/\.claude/hooks/pyrun\.sh" "\$CLAUDE_PROJECT_DIR/\.claude/hooks/([\w-]+\.py)"',
        r'(?:bash|node) "\$CLAUDE_PROJECT_DIR/\.claude/hooks/([\w-]+\.(?:sh|js))"',
        r'\.claude/hooks/([\w-]+\.py)',
        r'node "[^"\r\n]+/\.claude/hooks/run-hook\.cjs" "([\w-]+\.(?:py|sh|js))"',
    ]
    for pattern in patterns:
        match = re.fullmatch(pattern, command)
        if match:
            return match.group(1)
    return None


def converted_settings(settings, root):
    result = copy.deepcopy(settings)
    runner = (root / '.claude/hooks/run-hook.cjs').as_posix()
    if any(c in runner for c in ('"', '%', '!', '$', '`', '\n', '\r')):
        raise StartupError('Use uma pasta sem aspas, %, !, $, crase ou quebras de linha.')
    count = 0
    for groups in result.get('hooks', {}).values():
        for group in groups:
            for hook in group.get('hooks', []):
                if hook.get('type') != 'command':
                    continue
                target = hook_target(hook.get('command', ''))
                if target:
                    if not (root / '.claude/hooks' / target).is_file():
                        raise StartupError('Um hook registrado esta ausente. Nenhuma configuracao foi substituida.')
                    command = f'node "{runner}" "{target}"'
                    if hook['command'] != command:
                        hook['command'] = command
                        count += 1
    return result, count


def repair_hooks(root):
    changes = []
    for name in ('settings.json', 'settings.local.json'):
        path = root / '.claude' / name
        if not path.exists():
            continue
        raw = path.read_bytes()
        try:
            original = json.loads(raw.decode('utf-8-sig'))
            updated, count = converted_settings(original, root)
        except (ValueError, TypeError, AttributeError):
            raise StartupError('Settings JSON invalido. Corrija o arquivo antes de iniciar.') from None
        if count:
            changes.append((path, raw, updated, count))
    if not changes:
        return 0
    backup = root / '.data/mega-brain/backups' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + secrets.token_hex(4))
    backup.mkdir(parents=True, mode=0o700)
    for path, raw, _, _ in changes:
        (backup / path.name).write_bytes(raw)
    for path, raw, updated, _ in changes:
        if path.read_bytes() != raw:
            raise StartupError('Settings mudou durante a preparacao. Inicie novamente.')
        fd, temporary = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
                json.dump(updated, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return sum(c[3] for c in changes)


def select_port():
    for port in range(4000, 4021):
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1', port))
                return port
            except OSError:
                pass
    raise StartupError('Portas 4000 a 4020 ocupadas. Feche uma ponte antiga e tente novamente.')


def proxy_config(model):
    return {
        'model_list': [
            {'model_name': model, 'litellm_params': {
                'model': model, 'api_key': 'os.environ/GEMINI_API_KEY', 'max_retries': 0}},
            {'model_name': 'mega-brain-groq-fallback', 'litellm_params': {
                'model': FALLBACK_MODEL, 'api_base': 'https://api.groq.com/openai/v1',
                'api_key': 'os.environ/GROQ_API_KEY', 'max_retries': 0}},
        ],
        'router_settings': {
            'routing_strategy': 'simple-shuffle',
            'num_retries': 0,
            'max_fallbacks': 1,
            'timeout': 60,
            'fallbacks': [{model: ['mega-brain-groq-fallback']}],
        },
        'general_settings': {'master_key': 'os.environ/MEGA_BRAIN_GATEWAY_TOKEN'},
        'litellm_settings': {
            'drop_params': True,
            'set_verbose': False,
            'num_retries': 0,
            'use_chat_completions_url_for_anthropic_messages': True,
        },
    }


def client_settings(url, model, token, env):
    values = {k: env[k] for k in ('PATH', 'MEGA_BRAIN_PYTHON', 'CLAUDE_PROJECT_DIR', 'CLAUDE_CODE_GIT_BASH_PATH', 'PYTHONUTF8', 'PYTHONIOENCODING')}
    values.update(ANTHROPIC_BASE_URL=url, ANTHROPIC_AUTH_TOKEN=token,
                  ANTHROPIC_API_KEY='', CLAUDE_CODE_OAUTH_TOKEN='',
                  ANTHROPIC_MODEL=model, ANTHROPIC_DEFAULT_SONNET_MODEL=model,
                  ANTHROPIC_DEFAULT_OPUS_MODEL=model, ANTHROPIC_DEFAULT_HAIKU_MODEL=model,
                  ANTHROPIC_SMALL_FAST_MODEL=model, CLAUDE_CODE_USE_BEDROCK='0',
                  CLAUDE_CODE_USE_VERTEX='0', CLAUDE_CODE_USE_FOUNDRY='0',
                  CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1', CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY='1')
    return {'env': values, 'model': model}


def request(url, token, payload=None, timeout=60):
    headers = {'Authorization': 'Bearer ' + token, 'anthropic-version': '2023-06-01'}
    data = None
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(payload).encode()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(urllib.request.Request(url, data=data, headers=headers), timeout=timeout)


def wait_ready(process, url, token, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise StartupError('LiteLLM encerrou antes de iniciar. Verifique a instalacao litellm[proxy].')
        try:
            with request(url + '/v1/models', token, timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.3)
    raise StartupError('LiteLLM nao ficou pronto em 90 segundos.')


def verify_bridge(url, token, model):
    payload = {'model': model, 'max_tokens': 64, 'messages': [{'role': 'user', 'content': 'Responda somente: PONTE OK'}]}
    try:
        with request(url + '/v1/messages', token, payload) as response:
            data = json.load(response)
        text = ''.join(b.get('text', '') for b in data.get('content', []) if b.get('type') == 'text')
        if 'PONTE OK' not in text:
            raise StartupError('A ponte respondeu, mas nao confirmou PONTE OK.')
        payload['stream'] = True
        with request(url + '/v1/messages', token, payload) as response:
            stream = response.read(1_000_000).decode('utf-8')
        if 'event: message_start' not in stream or 'event: message_stop' not in stream or 'event: error' in stream:
            raise StartupError('O teste de streaming Anthropic nao foi concluido.')
    except urllib.error.HTTPError as error:
        raise StartupError(f'Ponte recusou o teste (HTTP {error.code}). Nenhum corpo de erro ou segredo foi exibido.') from None
    except (OSError, ValueError, urllib.error.URLError):
        raise StartupError('Falha de rede ou resposta invalida no teste da ponte.') from None


def stop_owned(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verifica ambiente sem chamar Gemini ou alterar settings.')
    parser.add_argument('--test', action='store_true', help='Faz uma chamada pelo Claude Code, depois encerra.')
    parser.add_argument('--model', default=MODEL)
    args = parser.parse_args(argv)
    if os.name != 'nt':
        raise StartupError('Este iniciador e destinado ao Windows. Testes unitarios funcionam em Linux.')
    if not args.model.startswith('gemini/') or not re.fullmatch(r'[a-zA-Z0-9_./-]+', args.model):
        raise StartupError('Modelo invalido: informe um identificador gemini/.')
    for distribution in ('litellm', 'python-dotenv', 'PyYAML'):
        try:
            version = importlib.metadata.version(distribution)
            if distribution == 'litellm' and version != '1.100.1':
                raise StartupError('Esta versao do iniciador requer litellm[proxy]==1.100.1.')
        except importlib.metadata.PackageNotFoundError:
            raise StartupError('Dependencia ausente. Instale litellm[proxy] no mesmo Python usado pelo iniciador.') from None
    if not (ROOT / '.claude/settings.json').is_file():
        raise StartupError('Execute dentro do projeto completo: .claude/settings.json ausente.')
    bash = find_bash(os.environ)
    env = child_environment(os.environ, bash)
    node = shutil.which('node', path=env['PATH'])
    claude = shutil.which('claude', path=env['PATH'])
    litellm = shutil.which('litellm', path=env['PATH'])
    if not all((node, claude, litellm)):
        raise StartupError('Node.js, Claude Code ou executavel LiteLLM nao encontrado no PATH.')
    keys = load_provider_keys(ROOT)
    print('OK: Python, Node.js, Claude Code, LiteLLM, Git Bash e chaves locais presentes.')
    if args.check:
        print('Diagnostico concluido. Nenhuma chamada externa ou alteracao de settings.')
        return 0
    missing_core = [p for p in ('mega-brain-core/core/synapse/runtime/hook-runtime.js', 'mega-brain-core/hooks/unified/runners/precompact-runner.js') if not (ROOT / p).is_file()]
    if missing_core:
        raise StartupError('Projeto incompleto: arquivos centrais do Mega Cerebro ausentes.')
    repair_hooks(ROOT)
    port = select_port()
    token = 'sk-local-' + secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory(prefix='mega-brain-') as directory:
        config_path = Path(directory) / 'litellm.yaml'
        import yaml
        config_path.write_text(yaml.safe_dump(proxy_config(args.model), sort_keys=False), encoding='utf-8')
        proxy_env = dict(env)
        proxy_env.update(keys)
        proxy_env['MEGA_BRAIN_GATEWAY_TOKEN'] = token
        process = None
        settings_path = None
        try:
            process = subprocess.Popen([litellm, '--config', str(config_path), '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT, env=proxy_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            url = f'http://127.0.0.1:{port}'
            wait_ready(process, url, token)
            if args.test:
                verify_bridge(url, token, args.model)
                print('PONTE OK: Gemini primario e fallback configurado no gateway local.')
                return 0
            client_env = sanitized_client_environment(env)
            settings = client_settings(url, args.model, token, client_env)
            fd, settings_path = tempfile.mkstemp(prefix='mega-brain-claude-', suffix='.json')
            os.close(fd)
            Path(settings_path).write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
            return subprocess.call([claude, '--settings', settings_path], cwd=ROOT, env=client_env)
        finally:
            if settings_path and os.path.exists(settings_path):
                os.unlink(settings_path)
            stop_owned(process)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except StartupError as error:
        print('ERRO:', error, file=sys.stderr)
        raise SystemExit(1)
