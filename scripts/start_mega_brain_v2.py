"""Compatibility launcher for Gemini free-tier on Windows.
Keeps startup quota-free and rate-limits the local gateway to the project's 5 RPM ceiling.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'scripts' / 'start_mega_brain.py'
spec = importlib.util.spec_from_file_location('mega_brain_base_launcher', BASE)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def proxy_config_free_tier(model):
    config = base.proxy_config(model)
    params = config['model_list'][0]['litellm_params']
    # Google AI Studio reports a 5 RPM ceiling for this project. Stay below it
    # and serialize requests so agent bursts do not immediately trigger HTTP 429.
    params['rpm'] = 4
    params['max_parallel_requests'] = 1
    params['num_retries'] = 2
    return config


def verify_bridge_without_provider_call(url, token, model):
    # wait_ready() already authenticated against the local LiteLLM /v1/models
    # endpoint. Do not spend two Gemini requests every time Mega Brain starts.
    return None


base.proxy_config = proxy_config_free_tier
base.verify_bridge = verify_bridge_without_provider_call

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
