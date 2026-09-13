"""Fail closed on missing hooks, incompatible templates or stale installer bytes.
Only reads explicit tracked release files, never .env or user runtime state.
"""
import ast
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

import jsonschema

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def validate():
    launcher = module('start_mega_brain')
    builder = module('build_windows_installer')
    settings = json.loads((ROOT / '.claude/settings.json').read_text(encoding='utf-8'))
    _, count = launcher.converted_settings(settings, ROOT)
    assert count > 60, 'Stock hook coverage unexpectedly changed'
    insights = json.loads((ROOT / 'system/REGISTRY/INSIGHTS-STATE.json').read_text(encoding='utf-8'))
    schema = json.loads((ROOT / 'engine/jarvis/schemas/insights-state.schema.json').read_text(encoding='utf-8'))
    jsonschema.validate({'insights_state': insights}, schema)
    # Read the modern writer's actual initialization function without importing
    # the rest of the pipeline (which may initialize credential-bearing clients).
    source = ROOT / 'engine/intelligence/pipeline/mce/orchestrate.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_load_insights_state')
    skeleton = next(n.value for n in function.body if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict))
    fields = {n.value for n in skeleton.keys}
    assert fields <= insights.keys(), f'Missing writer fields: {fields - insights.keys()}'
    assert insights['persons'] == insights['themes'] == {} and insights['total_insights'] == 0
    history = json.loads((ROOT / 'system/REGISTRY/BATCH-HISTORY.json').read_text(encoding='utf-8'))
    assert isinstance(history.get('batches'), list) and not history['batches']
    # Health scorer and process-jarvis contract: list entries, no fabricated runs.
    config = launcher.proxy_config(launcher.MODEL)
    assert config['router_settings']['fallbacks'] == [{launcher.MODEL: ['mega-brain-groq-fallback']}]
    assert config['model_list'][0]['litellm_params']['rpm'] == 5
    assert config['router_settings']['num_retries'] == 0
    with zipfile.ZipFile(ROOT / 'windows/INSTALAR_MEGA_CEREBRO_FINAL.zip') as archive:
        assert archive.namelist() == ['INSTALAR_MEGA_CEREBRO.cmd']
        command = archive.read('INSTALAR_MEGA_CEREBRO.cmd').replace(b'\r\n', b'\n')
    source = base64.b64decode(command.rsplit(b'\nREM MEGA_PAYLOAD\n', 1)[1])
    tree = ast.parse(source)
    encoded = ast.literal_eval(tree.body[0].value)
    payload = json.loads(base64.b64decode(encoded))
    assert set(payload) == set(builder.FILES)
    assert not any(Path(p).name.startswith('.env') or p.endswith('settings.json') for p in payload)
    for relative, item in payload.items():
        data = base64.b64decode(item['data'], validate=True)
        assert hashlib.sha256(data).hexdigest() == item['sha256'], relative
        expected = (ROOT / relative).read_bytes()
        if relative.endswith('.cmd'):
            expected = expected.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        assert data == expected, 'Rebuild stale installer: ' + relative
    expected_source = 'PAYLOAD = ' + repr(encoded) + '\n' + builder.INSTALL
    assert source == expected_source.encode(), 'Installer implementation is stale'
    print(f'OK: {count} hooks, state contracts, fallback configuration, {len(payload)} exact installer files.')


if __name__ == '__main__':
    validate()
