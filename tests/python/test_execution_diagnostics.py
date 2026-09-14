import json
import subprocess
import sys

from engine.executor.executor import TaskExecutor
from engine.executor.diagnostics import redact


def test_failed_command_persists_real_diagnostic(tmp_path):
    (tmp_path / 'fail.py').write_text("import sys\nprint('partial output')\nprint('actual failure', file=sys.stderr)\nsys.exit(7)\n")
    executor = TaskExecutor(str(tmp_path), store_root=str(tmp_path / 'store'))
    records = executor._execute_step_retry({'id': 'failed-command', 'action': 'run',
                                          'params': {'command': 'python fail.py'}})
    assert len(records) == 3
    for i, record in enumerate(records, 1):
        assert record['exit_code'] == 7
        assert record['stdout'].strip() == 'partial output'
        assert record['stderr'].strip() == 'actual failure'
        assert record['error'].strip() == 'actual failure'
        assert record['attempt'] == i
        assert record['task_id'] and record['session_id'] and record['timestamp']
    persisted = [json.loads(line) for line in executor.journal.path.read_text().splitlines()]
    assert persisted == records
    assert executor.journal.path.is_absolute()
    assert executor._run_step('diagnostics', {})['records'] == records


def test_secrets_redacted_from_logs_and_results(tmp_path, monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', 'fixture-credential-value')
    executor = TaskExecutor(str(tmp_path), store_root=str(tmp_path / 'store'))
    monkeypatch.setattr(executor, '_run_step', lambda *_: {
        'ok': False, 'exit_code': 1, 'stdout': 'fixture-credential-value',
        'stderr': 'Authorization: Bearer fixture-token\npassword="hidden password"',
        'error': 'API_KEY=another-secret'})
    records = executor._execute_step_retry({'action': 'run', 'params': {'token': 'nested-secret'}})
    serialized = json.dumps(records) + executor.journal.path.read_text() + executor.memory.events_file.read_text()
    for secret in ('fixture-credential-value', 'fixture-token', 'hidden password', 'another-secret', 'nested-secret'):
        assert secret not in serialized


def test_timeout_preserves_partial_output(tmp_path, monkeypatch):
    executor = TaskExecutor(str(tmp_path), store_root=str(tmp_path / 'store'), max_attempts=1)
    def timeout(*_, **kwargs):
        raise subprocess.TimeoutExpired('python', 2, output=b'partial', stderr=b'real timeout context')
    monkeypatch.setattr(subprocess, 'run', timeout)
    record = executor._execute_step_retry({'action': 'run', 'params': {'command': 'python fail.py', 'timeout': 2}})[0]
    assert record['timeout'] is True
    assert record['stdout'] == 'partial'
    assert record['stderr'] == 'real timeout context'
    assert 'timed out' in record['error']


def test_credential_file_read_is_blocked(tmp_path):
    executor = TaskExecutor(str(tmp_path), store_root=str(tmp_path / 'store'))
    assert executor.tools.read('.env')['blocked']


def test_diagnostics_are_returned_to_the_user(tmp_path):
    executor = TaskExecutor(str(tmp_path), store_root=str(tmp_path / 'store'), max_attempts=1)
    executor._execute_step_retry({'id': 'missing', 'action': 'read', 'params': {'path': 'absent.txt'}})
    record = executor._execute_step_retry({'id': 'diagnose', 'action': 'diagnostics'})[0]
    assert 'file not found' in record['diagnostics'][0]['error']
    assert 'diagnostics' not in json.loads(executor.journal.path.read_text().splitlines()[-1])
    assert redact({'path': '.env', 'content': 'UNLABELLED=private-value'})['content'] == '[REDACTED]'
