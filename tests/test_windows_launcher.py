"""Credential-free regression tests, also runnable on native Windows."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('launcher', REPO / 'scripts/start_mega_brain.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='mega brain & teste ')
        self.root = Path(self.temporary.name)
        (self.root / '.claude/hooks').mkdir(parents=True)
        shutil.copy(REPO / '.claude/hooks/run-hook.cjs', self.root / '.claude/hooks/run-hook.cjs')

    def tearDown(self):
        self.temporary.cleanup()

    def test_offline_installer_preserves_settings_env_and_backs_up_files(self):
        import base64
        import zipfile
        (self.root / '.claude/settings.json').write_bytes(b'{"hooks":{}}')
        (self.root / '.env').write_bytes(b'LOCAL_SECRET_PLACEHOLDER=unchanged')
        (self.root / 'INICIAR_MEGA_CEREBRO.cmd').write_bytes(b'original launcher')
        original_runner = (self.root / '.claude/hooks/run-hook.cjs').read_bytes()
        with zipfile.ZipFile(REPO / 'windows/INSTALAR_MEGA_CEREBRO.zip') as archive:
            cmd = archive.read('INSTALAR_MEGA_CEREBRO.cmd').replace(b'\r\n', b'\n')
        source = base64.b64decode(cmd.rsplit(b'\nREM MEGA_PAYLOAD\n', 1)[1])
        with patch.dict(os.environ, {'MEGA_INSTALLER': str(self.root / 'installer.cmd')}):
            with patch('subprocess.call', return_value=0) as launch:
                with self.assertRaises(SystemExit) as result:
                    exec(compile(source, '<test-installer>', 'exec'), {})
        self.assertEqual(0, result.exception.code)
        self.assertEqual(b'{"hooks":{}}', (self.root / '.claude/settings.json').read_bytes())
        self.assertEqual(b'LOCAL_SECRET_PLACEHOLDER=unchanged', (self.root / '.env').read_bytes())
        backup = next((self.root / '.data/mega-brain/installer-backups').iterdir())
        self.assertEqual(b'original launcher', (backup / 'INICIAR_MEGA_CEREBRO.cmd').read_bytes())
        self.assertEqual(original_runner, (backup / '.claude/hooks/run-hook.cjs').read_bytes())
        for name in ('scripts/start_mega_brain.py', '.claude/hooks/run-hook.cjs'):
            self.assertEqual((REPO / name).read_bytes(), (self.root / name).read_bytes())
        self.assertEqual(sys.executable, launch.call_args.args[0][0])

    def test_preserve_entire_configuration_and_exact_backups(self):
        original = json.loads((REPO / '.claude/settings.json').read_text())
        for groups in original['hooks'].values():
            for group in groups:
                for hook in group['hooks']:
                    name = launcher.hook_target(hook['command'])
                    self.assertIsNotNone(name, hook['command'])
                    (self.root / '.claude/hooks' / name).touch()
        original['futureSetting'] = {'keep': [1, 2]}
        original['hooks']['SessionStart'][0]['hooks'].append({'type': 'command', 'command': 'echo custom', 'timeout': 7})
        path = self.root / '.claude/settings.json'
        raw = ('\ufeff' + json.dumps(original, indent=4)).encode('utf-8')
        path.write_bytes(raw)
        count = launcher.repair_hooks(self.root)
        self.assertGreater(count, 60)
        updated = json.loads(path.read_text())
        restored_commands = copy.deepcopy(updated)
        for event, groups in original['hooks'].items():
            for i, group in enumerate(groups):
                for j, hook in enumerate(group['hooks']):
                    restored_commands['hooks'][event][i]['hooks'][j]['command'] = hook['command']
        self.assertEqual(original, restored_commands)
        self.assertEqual('echo custom', updated['hooks']['SessionStart'][0]['hooks'][-1]['command'])
        self.assertEqual(raw, next((self.root / '.data/mega-brain/backups').glob('*/settings.json')).read_bytes())
        self.assertEqual(0, launcher.repair_hooks(self.root))

    def test_invalid_local_json_prevents_all_mutations(self):
        raw = b'{"hooks":{}}'
        (self.root / '.claude/settings.json').write_bytes(raw)
        (self.root / '.claude/settings.local.json').write_text('{broken')
        with self.assertRaises(launcher.StartupError):
            launcher.repair_hooks(self.root)
        self.assertEqual(raw, (self.root / '.claude/settings.json').read_bytes())

    def test_missing_script_refuses_conversion(self):
        settings = {'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': '.claude/hooks/missing.py'}]}]}}
        with self.assertRaises(launcher.StartupError):
            launcher.converted_settings(settings, self.root)

    def test_runner_preserves_unicode_stdin_stdout_and_exit_code(self):
        script = self.root / '.claude/hooks/echo.py'
        script.write_text('import sys\nsys.stdout.write(sys.stdin.read())\nsys.exit(2)\n')
        data = '{"prompt":"ação e memória"}'
        env = dict(os.environ, MEGA_BRAIN_PYTHON=sys.executable)
        result = subprocess.run(['node', str(self.root / '.claude/hooks/run-hook.cjs'), 'echo.py'],
                                input=data, encoding='utf-8', capture_output=True, env=env)
        self.assertEqual(2, result.returncode)
        self.assertEqual(data, result.stdout)

    def test_runner_does_not_silently_skip_missing_interpreter(self):
        (self.root / '.claude/hooks/echo.py').touch()
        env = dict(os.environ, MEGA_BRAIN_PYTHON=str(self.root / 'missing-python'))
        result = subprocess.run(['node', str(self.root / '.claude/hooks/run-hook.cjs'), 'echo.py'], env=env, capture_output=True)
        self.assertEqual(2, result.returncode)

    def test_shell_guard_still_blocks_unauthorized_push(self):
        name = 'enforce-git-push-authority.sh'
        shutil.copy(REPO / '.claude/hooks' / name, self.root / '.claude/hooks' / name)
        env = dict(os.environ)
        env.pop('MEGABRAIN_ACTIVE_AGENT', None)
        env['CLAUDE_CODE_GIT_BASH_PATH'] = str(launcher.find_bash(env))
        result = subprocess.run(['node', str(self.root / '.claude/hooks/run-hook.cjs'), name],
                                input=json.dumps({'tool_input': {'command': 'git push origin main'}}),
                                encoding='utf-8', capture_output=True, env=env)
        self.assertEqual(0, result.returncode)
        self.assertEqual('deny', json.loads(result.stdout)['hookSpecificOutput']['permissionDecision'])

    def test_key_alias_loaded_without_interpolation_or_file_change(self):
        from dotenv import dotenv_values
        for name in launcher.KEY_NAMES:
            raw = f'{name}="dummy-${{NOT_EXPANDED}}"\n'
            path = self.root / '.env'
            path.write_text(raw)
            self.assertEqual('dummy-${NOT_EXPANDED}', launcher.load_provider_key(self.root))
            self.assertEqual(raw, path.read_text())

    def test_overlay_overrides_stale_auth_and_keeps_hooks_out(self):
        env = {k: 'dummy' for k in ['PATH', 'MEGA_BRAIN_PYTHON', 'CLAUDE_PROJECT_DIR', 'CLAUDE_CODE_GIT_BASH_PATH', 'PYTHONUTF8', 'PYTHONIOENCODING']}
        overlay = launcher.client_settings('http://127.0.0.1:4001', launcher.MODEL, 'test-token', env)
        self.assertNotIn('hooks', overlay)
        self.assertNotIn('permissions', overlay)
        self.assertEqual('test-token', overlay['env']['ANTHROPIC_AUTH_TOKEN'])
        self.assertEqual('', overlay['env']['ANTHROPIC_API_KEY'])
        self.assertEqual('', overlay['env']['CLAUDE_CODE_OAUTH_TOKEN'])
        self.assertEqual(launcher.MODEL, overlay['env']['ANTHROPIC_DEFAULT_HAIKU_MODEL'])
        self.assertNotIn('GEMINI_API_KEY', overlay['env'])

    def test_proxy_config_has_environment_references_only(self):
        config = launcher.proxy_config(launcher.MODEL)
        self.assertEqual('os.environ/GEMINI_API_KEY', config['model_list'][0]['litellm_params']['api_key'])
        self.assertEqual('os.environ/MEGA_BRAIN_GATEWAY_TOKEN', config['general_settings']['master_key'])

    def test_occupied_port_is_not_reused(self):
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1', 4000))
                sock.listen()
            except OSError:
                pass
            self.assertNotEqual(4000, launcher.select_port())


class GatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.received = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                if self.headers.get('Authorization') != 'Bearer test-token':
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b'private-provider-error')
                    return
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                cls.received.append((self.path, payload))
                self.send_response(200)
                self.end_headers()
                if payload.get('stream'):
                    self.wfile.write(b'event: message_start\ndata: {}\n\nevent: message_stop\ndata: {}\n\n')
                else:
                    self.wfile.write(b'{"content":[{"type":"text","text":"PONTE OK"}]}')
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_messages_and_streaming_use_matching_gateway_token(self):
        launcher.verify_bridge(self.url, 'test-token', launcher.MODEL)
        self.assertEqual('/v1/messages', self.received[-1][0])
        self.assertTrue(self.received[-1][1]['stream'])
        self.assertEqual(launcher.MODEL, self.received[-1][1]['model'])

    def test_401_body_is_never_exposed(self):
        with self.assertRaises(launcher.StartupError) as error:
            launcher.verify_bridge(self.url, 'wrong-token', launcher.MODEL)
        self.assertIn('401', str(error.exception))
        self.assertNotIn('private-provider-error', str(error.exception))


if __name__ == '__main__':
    unittest.main()
