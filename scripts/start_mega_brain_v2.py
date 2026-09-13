"""Windows entry point with pre-stream Gemini fallback hardening.

LiteLLM 1.100.1 may surface Gemini/Vertex 429/503 only after a native stream
has already started. At that point the /v1/messages fallback path is too late.
Mark only the Gemini deployment as not supporting native streaming so LiteLLM
performs the provider request before emitting the Anthropic-compatible stream.
A provider 429/503 can then reach Router's normal one-shot Groq fallback before
Claude Code receives any stream bytes. Groq remains native-stream capable.
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
        # This is LiteLLM's model-capability switch for choosing fake/non-native
        # streaming. Unlike passing an ad-hoc fake_stream request parameter, the
        # proxy consults model_info when deciding whether to open an upstream
        # streaming generator.
        primary.setdefault('model_info', {})['supports_native_streaming'] = False
        return config

    launcher.proxy_config = proxy_config
    return launcher


def effective_proxy_config(model=None):
    launcher = harden_streaming_fallback(load_launcher())
    return launcher.proxy_config(model or launcher.MODEL)


if __name__ == '__main__':
    raise SystemExit(harden_streaming_fallback(load_launcher()).main())
