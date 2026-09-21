"""Integration tests require a built, isolated Docker runner; never silently simulate it."""
import os
import shutil
from uuid import uuid4

import pytest

from megabrain_api.execution import WebGate, WebTools

pytestmark = pytest.mark.skipif(not os.getenv('APP_SANDBOX_IMAGE') or not shutil.which('docker'), reason='Docker command sandbox unavailable')


def test_container_cannot_read_host_secret_or_network(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_JOB_ID',str(uuid4()))
    monkeypatch.setenv('MEGA_TEST_HOST_SECRET','must-not-enter-container')
    tools=WebTools(tmp_path,WebGate(tmp_path))
    code="import os,socket; assert not os.getenv('MEGA_TEST_HOST_SECRET'); assert not os.path.exists('/var/run/docker.sock'); s=socket.socket(); s.settimeout(1); assert s.connect_ex(('1.1.1.1',443)) != 0; print('isolated')"
    result=tools.run('python -c '+__import__('shlex').quote(code))
    assert result['ok'], result
    assert 'isolated' in result['summary']


def test_container_runs_real_tests(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_JOB_ID',str(uuid4()))
    (tmp_path/'pytest.ini').write_text('[pytest]\naddopts = -p no:cacheprovider\n')
    (tmp_path/'test_ok.py').write_text('def test_ok():\n    assert 2+2==4\n')
    tools=WebTools(tmp_path,WebGate(tmp_path))
    result=tools.run_tests()
    assert result['ok'] and result['exit_code']==0,result
