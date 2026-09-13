"""Windows entry point with a streaming-safe Gemini fallback workaround.

LiteLLM 1.100.1 can surface Gemini/Vertex 429 only after a stream object has
already been returned.  In that case Router fallback is too late.  Force the
Gemini deployment to fake-stream: LiteLLM performs the upstream Gemini request
non-streaming (so 429/503 is visible to Router), then emits an Anthropic stream
to Claude Code after success.  Groq remains the one-shot fallback.
"""
import importlib.util
from pathlib import Path


def load_launcher():
    path = Path(__file__).with_name('start_mega_brain.py')
    spec = importlib.util.spec_from_file_location('mega_brain_windows_launcher', path)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    return launcher


def harden_streaming_fallback(launcher):
    original = launcher.proxy_config

    def proxy_config(model):
        config = original(model)
        primary = next(item for item in config['model_list'] if item['model_name'] == model)
        # Preserve Claude Code streaming on the client side while making the
        # Gemini provider call non-streaming. This moves provider 429/503 into
        # Router's normal fallback path instead of the broken mid-stream path.
        primary['litellm_params']['fake_stream'] = True
        return config

    launcher.proxy_config = proxy_config
    return launcher


def effective_proxy_config(model=None):
    launcher = harden_streaming_fallback(load_launcher())
    return launcher.proxy_config(model or launcher.MODEL)


if __name__ == '__main__':
    raise SystemExit(harden_streaming_fallback(load_launcher()).main())
