"""Windows entry point with provider failover hardened for LiteLLM 1.100.1.

The base launcher owns Windows/bootstrap behavior. This entry point only adjusts
routing: provider 429s must reach the configured Groq fallback instead of being
turned into a local pre-call/cooldown error that Claude Code retries itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Import the sibling launcher without changing the user's project environment.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import start_mega_brain as launcher


def reliable_proxy_config(model):
    config = launcher.proxy_config(model)

    # The old local pre-call limiter raised RateLimitError before an upstream
    # deployment was selected. In LiteLLM 1.100.1 that can become
    # "No deployments available" and bypass the model-group fallback.
    settings = config.setdefault('litellm_settings', {})
    callbacks = settings.get('callbacks', [])
    settings['callbacks'] = [
        item for item in callbacks
        if item != 'scripts.mega_brain_rate_limit.limiter'
    ]
    if not settings['callbacks']:
        settings.pop('callbacks', None)

    router = config.setdefault('router_settings', {})
    # Let the real provider 429 be handled by the fallback chain in the same
    # request. Do not pre-eject Gemini and do not make Claude wait for cooldown.
    router['enable_pre_call_checks'] = False
    router['disable_cooldowns'] = True
    router['num_retries'] = 0
    router['max_fallbacks'] = 1
    router['fallbacks'] = [{model: ['mega-brain-groq-fallback']}]

    # Defensive normalization of the fallback deployment. No credential value
    # is stored here; LiteLLM resolves the environment variable at runtime.
    for deployment in config.get('model_list', []):
        if deployment.get('model_name') == 'mega-brain-groq-fallback':
            params = deployment.setdefault('litellm_params', {})
            params['model'] = 'openai/gpt-oss-120b'
            params['api_base'] = 'https://api.groq.com/openai/v1'
            params['api_key'] = 'os.environ/GROQ_API_KEY'
            params['max_retries'] = 0

    return config


launcher.proxy_config = reliable_proxy_config

if __name__ == '__main__':
    raise SystemExit(launcher.main())
