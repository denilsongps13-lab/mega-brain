from pathlib import Path

from megabrain_api.execution import WebGate, WebTools


def test_secrets_traversal_symlink_and_destructive_actions(tmp_path):
    root=tmp_path/'work';root.mkdir()
    (root/'.env').write_text('secret')
    (root/'secret.pem').write_text('secret')
    outside=tmp_path/'outside.txt';outside.write_text('private')
    (root/'link.txt').symlink_to(outside)
    tools=WebTools(root,WebGate(root))
    for path in ('.env','secret.pem','../outside.txt','link.txt'):
        assert tools.read(path)['blocked']
        assert not tools.write(path,'change')['ok']
    assert tools.search('secret')['count']==0
    assert tools.glob('../*')['blocked']
    assert tools.delete('.env')['blocked']
    assert tools.run('python -c "print(1)"')['blocked']
    assert outside.read_text()=='private'


def test_real_safe_file_edits(tmp_path):
    tools=WebTools(tmp_path,WebGate(tmp_path))
    assert tools.write('hello.py','x = 1')['ok']
    assert tools.edit('hello.py','x = 1','x = 2')['ok']
    assert tools.read('hello.py')['content']=='x = 2'
    assert tools.search('x = 2')['count']==1
