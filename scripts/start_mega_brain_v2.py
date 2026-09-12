"""Compatibility launcher for real LiteLLM/Gemini responses on Windows."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'scripts' / 'start_mega_brain.py'
spec = importlib.util.spec_from_file_location('mega_brain_base_launcher', BASE)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def verify_bridge_compatible(url, token, model):
    """Verify auth + Anthropic Messages API without trusting model wording."""
    payload = {
        'model': model,
        'max_tokens': 64,
        'messages': [{'role': 'user', 'content': 'Responda brevemente para confirmar a conexao.'}],
    }
    try:
        with base.request(url + '/v1/messages', token, payload) as response:
            if response.status != 200:
                raise base.StartupError('A ponte local nao confirmou HTTP 200.')
            data = json.load(response)
        # LiteLLM versions/providers can vary wording and, in compatibility modes,
        # response shape. A successful authenticated model response is what matters.
        content = data.get('content')
        choices = data.get('choices')
        if not content and not choices:
            raise base.StartupError('A ponte respondeu sem conteudo de modelo.')

        payload['stream'] = True
        with base.request(url + '/v1/messages', token, payload) as response:
            if response.status != 200:
                raise base.StartupError('Streaming da ponte nao confirmou HTTP 200.')
            stream = response.read(1_000_000).decode('utf-8', errors='replace')
        if not stream.strip() or 'event: error' in stream.lower():
            raise base.StartupError('O streaming da ponte nao foi concluido.')
    except urllib.error.HTTPError as error:
        raise base.StartupError(
            f'Ponte recusou o teste (HTTP {error.code}). Nenhum corpo de erro ou segredo foi exibido.'
        ) from None
    except (OSError, ValueError, urllib.error.URLError):
        raise base.StartupError('Falha de rede ou resposta invalida no teste da ponte.') from None


base.verify_bridge = verify_bridge_compatible

if __name__ == '__main__':
    try:
        sys.exit(base.main())
    except KeyboardInterrupt:
        print('\nEncerrado.')
        sys.exit(130)
    except base.StartupError as error:
        print('ERRO: ' + str(error), file=sys.stderr)
        sys.exit(1)
    except Exception:
        print('ERRO: inicializacao interrompida. Nenhum detalhe sensivel foi exibido.', file=sys.stderr)
        sys.exit(1)
