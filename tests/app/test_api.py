import io
import json
import os
import time
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from megabrain_api.config import Settings
from megabrain_api.database import Event, Job, Message
from megabrain_api.main import create_app

TOKEN = 'test-installation-token-' + 'x' * 32


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_TESTING', '1')
    monkeypatch.setenv('MEGA_BRAIN_PLANNER', 'deterministic')
    for key in ('GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GROQ_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    if os.getenv('APP_TEST_DATABASE_URL'):
        from sqlalchemy import create_engine
        from megabrain_api.database import Base
        engine = create_engine(os.environ['APP_TEST_DATABASE_URL'])
        Base.metadata.drop_all(engine)
        engine.dispose()
    return Settings(database_url=os.getenv('APP_TEST_DATABASE_URL', f'sqlite:///{tmp_path}/app.db'),
                    token=TOKEN, data=tmp_path/'data', workspace=tmp_path/'work')


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), headers={'Authorization': f'Bearer {TOKEN}'}) as client:
        yield client


def wait(client, jid):
    for _ in range(200):
        result = client.get(f'/api/executions/{jid}').json()
        if result['state'] in {'done', 'partial', 'error', 'cancelled'}:
            return result
        time.sleep(.05)
    raise AssertionError('Job timed out')


def test_auth_and_origin(client):
    assert client.get('/api/status', headers={'Authorization': ''}).status_code == 401
    assert client.get('/api/status', headers={'Origin': 'https://evil.example'}).status_code == 403
    response = client.get('/api/status')
    assert response.status_code == 200
    assert client.get('/api/status', headers={'Origin': 'https://localhost'}).status_code == 200
    assert response.json()['database'] == 'online'
    assert response.headers['cache-control'] == 'no-store'
    assert TOKEN not in response.text


def test_input_validation(client):
    assert client.post('/api/chat', json={'content': ' '}).status_code == 422
    assert client.post('/api/chat', json={'content': 'hi', 'command': 'rm'}).status_code == 422
    assert client.get('/api/executions/not-a-uuid').status_code == 422
    assert client.post('/api/chat', json={'content': 'x'*16001}).status_code == 422


@pytest.mark.parametrize('name,data,status', [('../escape.txt',b'abc',400),('a.exe',b'abc',415),('a.pdf',b'fake',400),('a.txt',b'\xff',400),('a.txt',b'',400)])
def test_upload_rejection(client,name,data,status):
    assert client.post('/api/documents', files={'file': (name,data)}).status_code == status


def test_docx_archive_validation(client):
    buff=io.BytesIO()
    with zipfile.ZipFile(buff,'w') as z:
        z.writestr('wrong.xml','test')
    assert client.post('/api/documents',files={'file':('fake.docx',buff.getvalue())}).status_code == 400


def test_upload_rag_persistence(client, settings):
    text = ('O projeto Aurora utiliza energia solar e baterias para operar em comunidades isoladas. ' * 20).encode()
    response = client.post('/api/documents',files={'file':('aurora.txt',text)})
    assert response.status_code == 202, response.text
    result = wait(client,response.json()['job_id'])
    assert result['state'] == 'done', result
    assert result['result']['chunks'] > 0
    hits = client.get('/api/rag?q=Aurora energia solar').json()['sources']
    assert any(h['source']=='aurora.txt' for h in hits)
    assert (settings.data/'rag/current').exists()
    assert client.get('/api/documents').json()[0]['job']['state'] == 'done'


def test_executor_phases_memory_and_ws(client, settings):
    (settings.workspace/'example.py').write_text('print("hello")')
    response = client.post('/api/executions',json={'objective':'Inventarie o projeto'})
    assert response.status_code == 202
    jid = response.json()['id']
    ticket = client.post('/api/ws-ticket',json={'job_id':jid}).json()['ticket']
    received=[]
    with client.websocket_connect('/ws/executions',headers={'Origin':'http://localhost:3000'}) as ws:
        ws.send_json({'ticket':ticket})
        for _ in range(200):
            event=ws.receive_json(); received.append(event)
            if event['type']=='terminal': break
    assert received[-1]['state']=='partial'
    phases=[e.get('state') for e in received if e['type']=='phase']
    assert phases[:2]==['thinking','planning']
    assert 'executing' in phases and 'validating' in phases
    assert 'Inventarie' in json.dumps(client.get('/api/memory').json(),ensure_ascii=False)
    with client.websocket_connect('/ws/executions',headers={'Origin':'http://localhost:3000'}) as ws:
        ws.send_json({'ticket':ticket})
        assert ws.receive()['type']=='websocket.close'


def test_chat_missing_provider_preserves_history(client):
    response=client.post('/api/chat',json={'content':'Olá, o que você sabe?'})
    assert response.status_code == 202
    data=response.json(); result=wait(client,data['id'])
    assert result['state']=='error'
    messages=client.get('/api/chat/conversations/'+data['conversation_id']).json()
    assert [m['role'] for m in messages]==['user','assistant']
    assert messages[-1]['state']=='error'
    assert 'API_KEY' not in json.dumps(result)
    again=client.post('/api/chat',json={'content':'Vamos continuar','conversation_id':data['conversation_id']})
    assert again.status_code==202
    wait(client,again.json()['id'])
    assert len(client.get('/api/chat/conversations/'+data['conversation_id']).json())==4


def test_cancel_queued_job(client):
    # Hold the actual manager lock so the process cannot finish before cancellation.
    manager=client.app.state.jobs
    client.portal.call(manager.lock.acquire)
    try:
        jid=client.post('/api/executions',json={'objective':'Uma tarefa'}).json()['id']
        assert client.post(f'/api/executions/{jid}/cancel').status_code==200
        assert client.get(f'/api/executions/{jid}').json()['state']=='cancelled'
    finally:
        client.portal.call(manager.lock.release)


def test_restart_marks_incomplete_jobs(settings):
    app=create_app(settings)
    with TestClient(app) as c:
        with c.app.state.sessions() as db:
            job=Job(kind='execution',objective='interrupted',state='executing')
            db.add(job);db.commit();jid=job.id
    with TestClient(create_app(settings),headers={'Authorization':f'Bearer {TOKEN}'}) as c:
        assert c.get(f'/api/executions/{jid}').json()['state']=='error'


def test_ws_replay_cursor(client):
    jid=client.post('/api/executions',json={'objective':'Inventário'}).json()['id']
    wait(client,jid)
    with client.app.state.sessions() as db:
        events=list(db.scalars(select(Event).where(Event.job_id==jid).order_by(Event.id)))
        after=events[-2].id
    ticket=client.post('/api/ws-ticket',json={'job_id':jid}).json()['ticket']
    with client.websocket_connect('/ws/executions',headers={'Origin':'http://localhost:3000'}) as ws:
        ws.send_json({'ticket':ticket,'after':after})
        event=ws.receive_json()
        assert event['type']=='terminal' and event['id']>after
