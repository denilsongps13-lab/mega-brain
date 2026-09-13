"""Regression contract for the real Windows entry point.

Claude Code requests streaming. Gemini must be called non-streaming so a
provider 429/503 reaches LiteLLM Router before response headers are committed;
LiteLLM then fake-streams the successful Gemini response to Claude Code.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_v2():
    path = ROOT / 'scripts' / 'start_mega_brain_v2.py'
    spec = importlib.util.spec_from_file_location('start_mega_brain_v2_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_windows_entry_buffers_gemini_but_not_groq():
    v2 = load_v2()
    config = v2.effective_proxy_config()
    primary, fallback = config['model_list']
    assert primary['model_name'] == 'gemini/gemini-3.6-flash'
    assert primary['litellm_params']['fake_stream'] is True
    assert primary['litellm_params']['max_retries'] == 0
    assert fallback['model_name'] == 'mega-brain-groq-fallback'
    assert fallback['litellm_params']['model'] == 'openai/gpt-oss-120b'
    assert fallback['litellm_params']['max_retries'] == 0
    assert 'fake_stream' not in fallback['litellm_params']
    router = config['router_settings']
    assert router['fallbacks'] == [{'gemini/gemini-3.6-flash': ['mega-brain-groq-fallback']}]
    assert router['num_retries'] == 0
    assert router['max_fallbacks'] == 1
    assert router['disable_cooldowns'] is True
